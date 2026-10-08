"""Pure bounded geometry over observed pixels, without game interpretation."""

from collections import Counter


_MAX_CELLS = 1_048_576


def grid(frame) -> list[list[int]]:
    """Copy the exact settled 2-D numeric board; animation uses its last grid."""
    if not isinstance(frame, (list, tuple)) or not frame:
        raise ValueError('observation grid unavailable')
    if isinstance(frame[0], (list, tuple)) and frame[0] and isinstance(frame[0][0], (list, tuple)):
        frame = frame[-1]
    if not isinstance(frame, (list, tuple)) or not frame or not isinstance(frame[0], (list, tuple)) or not frame[0]:
        raise ValueError('observation grid unavailable')
    width = len(frame[0])
    if len(frame) * width > _MAX_CELLS or any(
        not isinstance(row, (list, tuple)) or len(row) != width
        or any(type(value) is not int or not 0 <= value <= 255 for value in row)
        for row in frame
    ):
        raise ValueError('observation grid unavailable')
    return [list(row) for row in frame]


def _limit(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError('observation helper limit unavailable')
    return value


def render(frame, *, x0=0, y0=0, x1=None, y1=None, max_cells=4096) -> dict:
    """Render literal hexadecimal pixel values with x/y coordinates and bounds."""
    board = grid(frame)
    height, width = len(board), len(board[0])
    x1 = width if x1 is None else x1
    y1 = height if y1 is None else y1
    if (any(type(value) is not int for value in (x0, y0, x1, y1))
            or not 0 <= x0 < x1 <= width or not 0 <= y0 < y1 <= height):
        raise ValueError('observation render window unavailable')
    cap = _limit(max_cells, 4096)
    x1 = min(x1, x0 + cap)
    y1 = min(y1, y0 + cap // (x1 - x0))
    digits = max(2, len(str(max(width, height))))
    heading = 'y\\x'.rjust(digits) + ' ' + ' '.join(str(x).rjust(digits) for x in range(x0, x1))
    text = '\n'.join([heading, *[
        str(y).rjust(digits) + ' ' + ' '.join(f'{value:02X}'.rjust(digits) for value in board[y][x0:x1])
        for y in range(y0, y1)
    ]])
    return {'text': text, 'shape': [height, width], 'window': [x0, y0, x1, y1],
            'omitted_cells': height * width - (x1-x0) * (y1-y0)}


def geometry(frame, *, colors=None, limit=40) -> dict:
    """Count all colors and bounded 4-connected components; no implicit background."""
    board = grid(frame)
    height, width = len(board), len(board[0])
    cap = _limit(limit, 40)
    if colors is not None and (not isinstance(colors, (list, tuple))
            or any(type(value) is not int or not 0 <= value <= 255 for value in colors)):
        raise ValueError('observation colors unavailable')
    selected = set(colors) if colors is not None else None
    counts = Counter(value for row in board for value in row)
    seen = set()
    components = []
    total = 0
    for y, row in enumerate(board):
        for x, value in enumerate(row):
            if (x, y) in seen or (selected is not None and value not in selected):
                continue
            stack = [(x, y)]
            seen.add((x, y))
            left = right = x
            top = bottom = y
            size = 0
            while stack:
                cx, cy = stack.pop()
                size += 1
                left, right = min(left, cx), max(right, cx)
                top, bottom = min(top, cy), max(bottom, cy)
                for nx, ny in ((cx+1, cy), (cx-1, cy), (cx, cy+1), (cx, cy-1)):
                    if (0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen
                            and board[ny][nx] == value):
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            total += 1
            if len(components) < cap:
                components.append({'value': value, 'size': size, 'bbox': [left, top, right, bottom]})
    return {'shape': [height, width], 'counts': dict(sorted(counts.items())),
            'components': components, 'components_omitted': total-len(components)}


def diff(before, after, *, limit=80) -> dict:
    """Return exact change counts and bounded changed cells, including shape edges."""
    previous, current = grid(before), grid(after)
    cap = _limit(limit, 80)
    before_shape, after_shape = [len(previous), len(previous[0])], [len(current), len(current[0])]
    changes = []
    count = 0
    for y in range(max(before_shape[0], after_shape[0])):
        for x in range(max(before_shape[1], after_shape[1])):
            old = previous[y][x] if y < before_shape[0] and x < before_shape[1] else None
            new = current[y][x] if y < after_shape[0] and x < after_shape[1] else None
            if old != new:
                count += 1
                if len(changes) < cap:
                    changes.append({'x': x, 'y': y, 'before': old, 'after': new})
    return {'before_shape': before_shape, 'after_shape': after_shape, 'changed_cell_count': count,
            'changed_cells': changes, 'changed_cells_omitted': count-len(changes)}
