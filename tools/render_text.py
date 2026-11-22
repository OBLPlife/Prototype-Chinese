"""Build-time spelling for native font code points reserved for game symbols."""
import re

# U+00B7 is an original controller icon in Body/Title. U+2027 is unused by
# every original font; give it the donor's real middle-dot outline instead.
NAME_DOT_ALIAS = '\u2027'
FONT_ALIASES = {ord(NAME_DOT_ALIAS): 0x00b7}


def render_text(text):
    text = re.sub(r'(?<=[\u3400-\u9fff])\u00b7(?=[\u3400-\u9fffA-Za-z])', NAME_DOT_ALIAS, text)
    # Names with a middle initial: 亚历克斯·J.·默瑟.
    return re.sub(r'(?<=[A-Za-z]\.)\u00b7(?=[\u3400-\u9fff])', NAME_DOT_ALIAS, text)
