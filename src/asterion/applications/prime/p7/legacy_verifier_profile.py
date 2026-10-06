"""Frozen verifier contents from deployed 0f4fb448; read compatibility only.

This profile cannot issue a new certificate or grant SDK execution.
"""

DEPLOYED_0F4FB448 = {'animation_replay.py': '1aec4f73c515dc975c4a1c2357baf623cba3d39bc71c106adea92af6798baf02',
 'broker.py': '2fdc9a705ee93b93a9e7ff0d44dc50616f4da99faf8f7b3b91b8923860b7e491',
 'game.py': '21de63c2f94118439f54781d45789b6c52e83e8ff55111c3431da37a40125532',
 'live.py': '2c047d45bab2399f2aa6439dc919f7be36d277cda95c601abf290ca808a81ab1',
 'observation_state.py': '762d3d8ffa00496eb1871c2550d4c70c7e7e580af093ffd089ea33bacdb17ff1',
 'private_trace.py': 'acd511994e2cf87c97a927d75ef0c5dc1bcf2497fac3d6bc5c8ec204e10c71e6',
 'replay.py': '759cd354085a58ccac3d488c3f902eb6b048d7e3aa6c2042831d9cd2616a9dd8',
 'route_composition.py': '0c6dcd525d448006ca0753a19e415bfdcfb8e0567d407d0d82e395f4ea716eb7',
 'score.py': '19f8a118dc54b694130d683611abfd9d62f7632cae2f5732d1d6a8e12bba829a',
 'solution_certificates.py': '76ae9a886ce9856d1c9e72b13313916cc99237ff40562cebfdcdb89654a6f243',
 'solutions.py': 'af1bd782559e8aa203e9f61023b02d5d2537321d0094905deadf19f1208efd97',
 'trace.py': '33037afc261f4def88d73043eb8027613dd2ba9e39b3ebc6c9fc2dba7d1b0ee5'}

# Exact deployed d4c6000b verifier contents, including its own earlier profile
# file. Like 0f4fb448, this allows reading old certificates only; new save
# witnesses always bind the current verifier contents.
DEPLOYED_D4C6000B = {
 'animation_replay.py': 'e4e49afd711e85f7892d886254e70946699e0e5d1bad800c2e0d989a7324a674',
 'broker.py': '27988524c5e0a7b0d055485dce932a7701ec39ab6b020f222f175d2d2029d928',
 'dynamic_evidence.py': 'e8d32bb6a9726243df5fbe1cc876e8472dab51e447294978bdca80b953965830',
 'game.py': '21de63c2f94118439f54781d45789b6c52e83e8ff55111c3431da37a40125532',
 'legacy_verifier_profile.py': 'e8d52735ce9234fea6ebfc1b4484cb6473576df93a0328f53599ebaf9d0de443',
 'live.py': '56f87ea8051db1c08fba0c7b7a1b2cec1cef2be44a4f43ca28b819b3dbf654f4',
 'observation_state.py': '762d3d8ffa00496eb1871c2550d4c70c7e7e580af093ffd089ea33bacdb17ff1',
 'private_trace.py': 'acd511994e2cf87c97a927d75ef0c5dc1bcf2497fac3d6bc5c8ec204e10c71e6',
 'processing_diagnostics.py': 'cd91fff2d348b66080cd4e5924c712f356a46719fc2013f7e8471aa5afb4342f',
 'recording_stream.py': 'caa7738056b5e6799ffdd6d87a80b24bf2e7ea83228c96bd95ff78b5e6bbca12',
 'replay.py': '759cd354085a58ccac3d488c3f902eb6b048d7e3aa6c2042831d9cd2616a9dd8',
 'route_composition.py': '0c6dcd525d448006ca0753a19e415bfdcfb8e0567d407d0d82e395f4ea716eb7',
 'score.py': '19f8a118dc54b694130d683611abfd9d62f7632cae2f5732d1d6a8e12bba829a',
 'solution_certificates.py': '4269c801fd07847f23d7421521670063d140428500ddd222369f772cce601e4a',
 'solutions.py': 'd081e37d21e2a133e4cc6e4aa01d9a30dd4912a32b096d2b439d76e9fd48a701',
 'trace.py': '33037afc261f4def88d73043eb8027613dd2ba9e39b3ebc6c9fc2dba7d1b0ee5',
}

# Exact deployed 1d803298 verifier contents; immutable certificate reads only.
DEPLOYED_1D803298 = {'animation_replay.py': 'e4e49afd711e85f7892d886254e70946699e0e5d1bad800c2e0d989a7324a674',
 'broker.py': '63d220754820aa4c5cdc8d4d9efc91171879b36b9261825177a3d60a6ef5235a',
 'dynamic_evidence.py': 'e8d32bb6a9726243df5fbe1cc876e8472dab51e447294978bdca80b953965830',
 'game.py': '21de63c2f94118439f54781d45789b6c52e83e8ff55111c3431da37a40125532',
 'legacy_verifier_profile.py': '8d8f9515ed116c95150c0b95a65c6c230fbb73af4e845e54714f4b5b31f2941d',
 'live.py': '56f87ea8051db1c08fba0c7b7a1b2cec1cef2be44a4f43ca28b819b3dbf654f4',
 'observation_state.py': '762d3d8ffa00496eb1871c2550d4c70c7e7e580af093ffd089ea33bacdb17ff1',
 'private_trace.py': 'acd511994e2cf87c97a927d75ef0c5dc1bcf2497fac3d6bc5c8ec204e10c71e6',
 'processing_diagnostics.py': 'cd91fff2d348b66080cd4e5924c712f356a46719fc2013f7e8471aa5afb4342f',
 'recording_stream.py': 'caa7738056b5e6799ffdd6d87a80b24bf2e7ea83228c96bd95ff78b5e6bbca12',
 'replay.py': '759cd354085a58ccac3d488c3f902eb6b048d7e3aa6c2042831d9cd2616a9dd8',
 'route_composition.py': '0c6dcd525d448006ca0753a19e415bfdcfb8e0567d407d0d82e395f4ea716eb7',
 'score.py': '19f8a118dc54b694130d683611abfd9d62f7632cae2f5732d1d6a8e12bba829a',
 'solution_certificates.py': '13e6f7798c55be0e870da9902840cad420466f1c1b79d2adceec10b6ea6e7f18',
 'solutions.py': 'cac3c579eeb392c559c81d97c45f6435d9dbf8086f805d00b65936df363628c3',
 'trace.py': '33037afc261f4def88d73043eb8027613dd2ba9e39b3ebc6c9fc2dba7d1b0ee5'}

# Exact deployed 3108995d verifier contents; immutable certificate reads only.
DEPLOYED_3108995D = {'animation_replay.py': 'e4e49afd711e85f7892d886254e70946699e0e5d1bad800c2e0d989a7324a674',
 'broker.py': '95d3f7f20627fc1887cce562cc74a046c072e2eedef6963a1f5b499ff6d275f1',
 'dynamic_evidence.py': 'a440c30e9b05453e8bb94434c654eedc6ffac0e329f04cb5f1897ea1fd17216c',
 'game.py': '21de63c2f94118439f54781d45789b6c52e83e8ff55111c3431da37a40125532',
 'legacy_verifier_profile.py': '3751a73bb631a147cb1e5897c041ed1aa18792d32b0715639d22660f9e6d0864',
 'live.py': '56f87ea8051db1c08fba0c7b7a1b2cec1cef2be44a4f43ca28b819b3dbf654f4',
 'observation_state.py': '762d3d8ffa00496eb1871c2550d4c70c7e7e580af093ffd089ea33bacdb17ff1',
 'private_trace.py': 'acd511994e2cf87c97a927d75ef0c5dc1bcf2497fac3d6bc5c8ec204e10c71e6',
 'processing_diagnostics.py': '03cb2742f919f2dd0a0f05829c531fd5acde65dd909b67c971ad882a6372f6bf',
 'recording_stream.py': 'caa7738056b5e6799ffdd6d87a80b24bf2e7ea83228c96bd95ff78b5e6bbca12',
 'replay.py': '759cd354085a58ccac3d488c3f902eb6b048d7e3aa6c2042831d9cd2616a9dd8',
 'route_composition.py': '0c6dcd525d448006ca0753a19e415bfdcfb8e0567d407d0d82e395f4ea716eb7',
 'score.py': '19f8a118dc54b694130d683611abfd9d62f7632cae2f5732d1d6a8e12bba829a',
 'solution_certificates.py': '1736f7755409121e64224e04bc1afe40e9dd2e72a735f89950cd83ad136214f1',
 'solutions.py': 'cac3c579eeb392c559c81d97c45f6435d9dbf8086f805d00b65936df363628c3',
 'trace.py': '33037afc261f4def88d73043eb8027613dd2ba9e39b3ebc6c9fc2dba7d1b0ee5'}
