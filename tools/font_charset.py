"""Complete Windows GBK repertoire plus the localization's actual characters.

The source is Microsoft's CP936 mapping published by the Unicode Consortium.
Control codes are not glyphs. Both ordinary and ideographic spaces retain glyph
advances. Original game icon codepoints are preserved by merge_fonts; text uses
the established alias in render_text where necessary.
"""
import hashlib,re,unicodedata
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
MAPPING=ROOT/'vendor/CP936.TXT'
MAPPING_SHA256='b86f601c575e9ab457380b6f7abef03c75499cc6075bdc8b4b27f3f2de74bf6a'
MAPPING_URL='https://www.unicode.org/Public/MAPPINGS/VENDORS/MICSFT/WINDOWS/CP936.TXT'

def full_gbk():
    data=MAPPING.read_bytes()
    assert hashlib.sha256(data).hexdigest()==MAPPING_SHA256
    values={int(m[2],16) for m in re.finditer(rb'^0x([0-9A-Fa-f]+)\s+0x([0-9A-Fa-f]+)',data,re.M)}
    assert len(values)==21920
    glyphs={chr(c) for c in values if not unicodedata.category(chr(c)).startswith('C')}
    assert len(glyphs)==21887
    return glyphs

def build_characters(texts):
    base=full_gbk()
    used={c for text in texts for c in text if not c.isspace()}
    result=''.join(sorted(base|used))
    return result,dict(name='GBK / Windows CP936',mapping_url=MAPPING_URL,
        mapping_sha256=MAPPING_SHA256,mapped_codepoints=21920,glyph_codepoints=len(base),
        han_codepoints=sum(0x4e00<=ord(c)<=0x9fff for c in base),
        additional_used_codepoints=[f'U+{ord(c):04X}' for c in sorted(used-base)],
        control_codes_excluded=True,spaces_have_advances=True)
