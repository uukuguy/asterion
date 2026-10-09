"""Bounded literal pixel translation evidence, without camera or risk inference."""

from collections import Counter
from functools import cmp_to_key

from .research_observation import grid
from .score import digest

_MAX_CELLS = 4096
_MAX_SHIFT = 32
_INTERPRETATION = 'Pixel translation candidate only; not camera truth, world coordinates, phase, or safety.'


def _shape(frame):
    if not isinstance(frame, (list, tuple)) or not frame:
        raise ValueError('view frame unavailable')
    if isinstance(frame[0], (list, tuple)) and frame[0] and isinstance(frame[0][0], (list, tuple)):
        frame = frame[-1]
    if (not isinstance(frame, (list, tuple)) or not frame
            or not isinstance(frame[0], (list, tuple)) or not frame[0]):
        raise ValueError('view frame unavailable')
    width = len(frame[0])
    if len(frame)*width > _MAX_CELLS:
        return [len(frame), width]
    if any(not isinstance(row, (list, tuple)) or len(row) != width for row in frame):
        raise ValueError('view frame unavailable')
    return [len(frame), width]


def _compare(left, right):
    difference = left['matched_pairs'] * right['informative_pairs'] - right['matched_pairs'] * left['informative_pairs']
    if difference:
        return -1 if difference > 0 else 1
    # Determinism does not resolve measurement ambiguity. Prefer zero in a tie.
    lkey = (abs(left['dx']) + abs(left['dy']), left['dx'], left['dy'])
    rkey = (abs(right['dx']) + abs(right['dy']), right['dx'], right['dy'])
    return (lkey > rkey) - (lkey < rkey)


def _measure(before, after, modal, dx, dy):
    height, width = len(before), len(before[0])
    x0, x1 = max(0, -dx), min(width, width-dx)
    y0, y1 = max(0, -dy), min(height, height-dy)
    matched = informative = zero_matched = zero_informative = old_count = new_count = 0
    left = width
    top = height
    right = bottom = -1
    for y in range(y0, y1):
        for x in range(x0, x1):
            old, new, unchanged = before[y][x], after[y+dy][x+dx], after[y][x]
            old_count += old != modal
            new_count += new != modal
            informative += old != modal or new != modal
            zero_informative += old != modal or unchanged != modal
            zero_matched += old == unchanged and old != modal
            if old == new and old != modal:
                matched += 1
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
    return {'dx': dx, 'dy': dy, 'informative_pairs': informative,
            'matched_pairs': matched, 'zero_informative_pairs': zero_informative,
            'zero_matched_pairs': zero_matched, 'before_overlap_informative': old_count,
            'after_overlap_informative': new_count,
            'support_window': [left, top, right+1, bottom+1] if matched else None,
            'overlap_pixels': (x1-x0)*(y1-y0)}


def view_change(before, after) -> dict:
    """Compare final returned grids using at most 129 axis shifts/528384 pairs.

    Joint modal ties choose the lowest palette value, without treating any
    particular color as a semantic background. Each alignment's denominator
    includes pairs with either endpoint non-modal. The zero baseline uses the
    same source window but its own union denominator. Support windows use
    half-open BEFORE pixel coordinates; exposed windows use AFTER coordinates.
    Large/different shapes are unsupported; invalid pixels raise ValueError.
    """
    before_shape, after_shape = _shape(before), _shape(after)
    result = {'status': 'unsupported', 'reason': 'shape-or-cell-budget',
              'before_shape': before_shape, 'after_shape': after_shape,
              'measurement': 'axis-translation-exact-pixels/v1',
              'interpretation': _INTERPRETATION, 'candidate_count': 0,
              'checked_pairs': 0, 'exposed_windows': []}
    if before_shape != after_shape or before_shape[0]*before_shape[1] > _MAX_CELLS:
        return result
    before, after = grid(before), grid(after)
    height, width = before_shape
    counts = Counter(v for frame in (before, after) for row in frame for v in row)
    modal = min(counts, key=lambda value: (-counts[value], value))
    old_total = sum(v != modal for row in before for v in row)
    new_total = sum(v != modal for row in after for v in row)
    result.update(before_frame_sha256=digest(before), after_frame_sha256=digest(after),
                  modal_color=modal, informative_before=old_total, informative_after=new_total)
    shifts = [(0, 0)] + [(d, 0) for d in range(-min(_MAX_SHIFT, width//2), min(_MAX_SHIFT, width//2)+1) if d]
    shifts += [(0, d) for d in range(-min(_MAX_SHIFT, height//2), min(_MAX_SHIFT, height//2)+1) if d]
    eligible = []
    for dx, dy in shifts:
        sample = _measure(before, after, modal, dx, dy)
        result['candidate_count'] += 1
        result['checked_pairs'] += sample['overlap_pixels']
        window = sample['support_window']
        # Eligibility is support/overlap only. Low score/gain competitors must
        # remain eligible so they cannot create spurious uniqueness.
        if (sample['informative_pairs'] >= 128 and old_total and new_total and window
                and sample['before_overlap_informative']*2 >= old_total
                and sample['matched_pairs']*2 >= new_total
                and (window[2]-window[0])*2 >= width
                and (window[3]-window[1])*2 >= height):
            eligible.append(sample)
    if not eligible:
        result.update(status='ambiguous', reason='insufficient-spatial-support')
        return result
    eligible.sort(key=cmp_to_key(_compare))
    best = eligible[0]
    runner = eligible[1] if len(eligible) > 1 else {'matched_pairs': 0, 'informative_pairs': 1}
    result.update({key: value for key, value in best.items() if key not in {'dx', 'dy', 'overlap_pixels'}})
    result.update(runner_matched_pairs=runner['matched_pairs'],
                  runner_informative_pairs=runner['informative_pairs'], eligible_candidates=len(eligible))
    if best['dx'] == best['dy'] == 0:
        result.update(status='no-candidate', reason='zero-alignment-best')
        return result
    matches, denominator = best['matched_pairs'], best['informative_pairs']
    zero_matches, zero_denominator = best['zero_matched_pairs'], best['zero_informative_pairs']
    if (100*matches < 85*denominator or not zero_denominator
            or 100*(matches*zero_denominator-zero_matches*denominator) < 15*denominator*zero_denominator):
        result.update(status='no-candidate', reason='insufficient-match-or-zero-gain')
        return result
    if 100*(matches*runner['informative_pairs']-runner['matched_pairs']*denominator) < 5*denominator*runner['informative_pairs']:
        result.update(status='ambiguous', reason='competing-alignments')
        return result
    dx, dy = best['dx'], best['dy']
    exposed = ([0, 0, dx, height] if dx > 0 else [width+dx, 0, width, height]
               if dx < 0 else [0, 0, width, dy] if dy > 0 else [0, height+dy, width, height])
    result.update(status='candidate', reason='supported-unique-axis-translation',
                  dx=dx, dy=dy, exposed_windows=[exposed])
    return result
