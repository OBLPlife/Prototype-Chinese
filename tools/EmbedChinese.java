// PrototypeZh build-time glyph generation. Uses the installed JPEXS library.
// Original game Latin glyphs are preserved by resources.merge_fonts after generation.
import java.awt.Font;
import java.nio.file.*;
import java.io.*;
import java.util.*;
import com.jpexs.decompiler.flash.SWF;
import com.jpexs.decompiler.flash.tags.Tag;
import com.jpexs.decompiler.flash.tags.DefineFont3Tag;

public class EmbedChinese {
    // The same donor also contains Western alphabets used in names and credits.
    // Only Han and its punctuation take the UI role's weight.
    private static boolean usesChineseWeight(char c) {
        return Character.UnicodeScript.of(c) == Character.UnicodeScript.HAN
            || (c >= '\u3000' && c <= '\u303f') || (c >= '\uff01' && c <= '\uff60')
            || "—‘’“”…‧".indexOf(c) >= 0;
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 5 && args.length != 6 && args.length != 8)
            throw new IllegalArgumentException("input.gfx output.gfx regular.ttf chars.txt latin.ttf [math.ttf [body.ttf title.ttf]]");
        Font donor = Font.createFont(Font.TRUETYPE_FONT, new File(args[2]));
        Font latin = Font.createFont(Font.TRUETYPE_FONT, new File(args[4]));
        Font math = args.length>=6 ? Font.createFont(Font.TRUETYPE_FONT, new File(args[5])) : null;
        Font body = args.length==8 ? Font.createFont(Font.TRUETYPE_FONT, new File(args[6])) : donor;
        Font title = args.length==8 ? Font.createFont(Font.TRUETYPE_FONT, new File(args[7])) : donor;
        Map<String,Font> roles = Map.of("PrototypeBodyPC",body,"PrototypeTitlePC",title,"PrototypeSubtitle",donor);
        String chars = Files.readString(Path.of(args[3]));
        SWF swf;
        try (InputStream in = Files.newInputStream(Path.of(args[0]))) {
            swf = new SWF(in, true);
        }
        int changed = 0;
        for (Tag tag : swf.getTags()) {
            if (!(tag instanceof DefineFont3Tag)) continue;
            DefineFont3Tag font = (DefineFont3Tag)tag;
            Font role = roles.get(font.fontName.replace("\0", ""));
            if (role == null) continue;
            int original = font.getCharacterCount();
            int ascent = font.fontAscent, descent = font.fontDescent, leading = font.fontLeading;
            for (char c : chars.toCharArray()) {
                if (Character.isISOControl(c) || font.charToGlyph(c) >= 0) continue;
                Font cjk = usesChineseWeight(c) ? role : donor;
                Font source=cjk.canDisplay(c)?cjk:latin;
                if (!source.canDisplay(c) && math!=null) source=math;
                if (!source.canDisplay(c)) throw new IllegalStateException("No donor glyph U+" + Integer.toHexString(c));
                if (!font.addCharacter(c, source)) throw new IllegalStateException("Cannot add U+" + Integer.toHexString(c));
            }
            if (font.fontAscent != ascent || font.fontDescent != descent || font.fontLeading != leading)
                throw new IllegalStateException("Original line metrics changed");
            System.out.println(font.fontName + " glyphs " + original + " -> " + font.getCharacterCount());
            changed++;
        }
        if (changed != 3) throw new IllegalStateException("Expected exactly 3 original text fonts, got " + changed);
        try (OutputStream out = Files.newOutputStream(Path.of(args[1]))) { swf.saveTo(out); }
    }
}

