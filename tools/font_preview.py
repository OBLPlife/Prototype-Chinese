"""Offline glyph preview from the exported built font; not an in-game screenshot."""
from pathlib import Path
import argparse
from PIL import Image,ImageDraw,ImageFont
from render_text import render_text

parser=argparse.ArgumentParser();parser.add_argument('--work',type=Path,required=True);args=parser.parse_args()
p=args.work/'font-preview'
im=Image.new('RGB',(1280,850),(22,24,27));draw=ImageDraw.Draw(im)
heading=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
draw.text((36,18),'OFFLINE GLYPH PREVIEW - extracted from the built game font resources',font=heading,fill=(180,186,196))
rows=[('1_BodyFont_PrototypeBodyPC.ttf','Body / original Latin + appended CJK',
       ['新游戏   显示模式   全屏 / 无边框全屏 / 窗口','亚历克斯·默瑟的公寓   亚历克斯·J.·默瑟','任务目标：摧毁直升机。  进化点数：1,250 EP']),
      ('2_SubtitleFont_PrototypeSubtitle.ttf','Subtitle / original metrics retained',
       ['My name is Alex Mercer.','我叫亚历克斯·默瑟。……阴谋之网／血毒剂']),
      ('3_TitleFont_PrototypeTitlePC.ttf','Title / original metrics retained',
       ['主程序员   Bryan Brandt','Hubert Zięba   Marina Caamaño   Activision'])]
y=75
for file,label,lines in rows:
    draw.text((36,y),label,font=heading,fill=(135,150,166));y+=80
    font=ImageFont.truetype(str(p/file),40)
    for line in lines:
        draw.text((38,y),render_text(line),font=font,fill=(236,237,239),anchor='ls');y+=57
    y+=12
im.save(p/'glyph-preview.png')
print(p/'glyph-preview.png')
