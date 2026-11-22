"""Build a compact quadratic donor from the licensed CFF source for SWF fonts.

Converting the donor's cubic contours before JPEXS import avoids its much larger
automatic cubic approximation. Original game glyphs are restored by merge_fonts.
The complete GBK files use paired native system-heap loading buffers; unrelated
GFX resources retain the original 2 MiB Temporary allocator.
"""
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.cu2quPen import Cu2QuPen
from render_text import FONT_ALIASES

MAX_ERROR_EM=0.002  # At 32 px/em the conversion bound is 0.064 px.

def make_donor(source,characters,output,weight='Regular'):
    font=TTFont(source)
    units=font['head'].unitsPerEm
    available=font.getBestCmap()
    cmap={ord(c):available[ord(c)] for c in characters if ord(c) in available}
    for alias,source_code in FONT_ALIASES.items():
        if chr(alias) in characters:
            cmap[alias]=available[source_code]
    wanted=set(cmap.values())|{'.notdef'}
    order=[name for name in font.getGlyphOrder() if name in wanted]
    glyphset=font.getGlyphSet();glyphs={}
    for name in order:
        pen=TTGlyphPen(glyphset)
        glyphset[name].draw(Cu2QuPen(pen,max_err=units*MAX_ERROR_EM,reverse_direction=True))
        glyphs[name]=pen.glyph()
    builder=FontBuilder(units,isTTF=True)
    builder.setupGlyphOrder(order);builder.setupCharacterMap(cmap);builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name:font['hmtx'].metrics[name] for name in order})
    builder.setupHorizontalHeader(ascent=font['hhea'].ascent,descent=font['hhea'].descent,lineGap=font['hhea'].lineGap)
    builder.setupNameTable(dict(familyName='PrototypeZh CJK',styleName=weight,
        uniqueFontIdentifier='PrototypeZh CJK quadratic build'+('' if weight=='Regular' else ' '+weight),
        fullName='PrototypeZh CJK '+weight,psName='PrototypeZhCJK-'+weight,version='Version 1.0'))
    os2=font['OS/2']
    builder.setupOS2(sTypoAscender=os2.sTypoAscender,sTypoDescender=os2.sTypoDescender,
        usWinAscent=os2.usWinAscent,usWinDescent=os2.usWinDescent,usWeightClass=os2.usWeightClass)
    if weight=='Bold':
        builder.font['head'].macStyle |= 1
        builder.font['OS/2'].fsSelection = (builder.font['OS/2'].fsSelection & ~64) | 32
    builder.setupPost();builder.setupMaxp();builder.save(output)
    check=TTFont(output)
    assert check.getBestCmap()==cmap and 'glyf' in check and 'CFF ' not in check
    return dict(source=str(source),characters=len(cmap),glyphs=len(order),
        units_per_em=units,max_curve_error_em=MAX_ERROR_EM,donor_bytes=Path(output).stat().st_size)

if __name__=='__main__':
    import argparse,json
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path)
    parser.add_argument('characters',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args()
    print(json.dumps(make_donor(args.source,args.characters.read_text('utf-8'),args.output),ensure_ascii=True))
