// Offline inventory of text tags; never starts the game or opens a UI.
import java.nio.file.*;
import java.io.*;
import java.util.*;
import com.jpexs.decompiler.flash.SWF;
import com.jpexs.decompiler.flash.tags.*;
import com.jpexs.decompiler.flash.tags.base.TextTag;
public class AuditGfxText {
    static PrintWriter out;
    static String b64(String s) { return Base64.getEncoder().encodeToString(s.getBytes(java.nio.charset.StandardCharsets.UTF_8)); }
    static void walk(Iterable<Tag> tags, String asset) {
        for (Tag tag:tags) {
            if (tag instanceof TextTag t) {
                String text=String.join("\n",t.getTexts());
                String detail=t instanceof DefineEditTextTag e ? "edit|"+e.variableName+"|"+e.fontId+"|"+e.fontHeight+"|"+e.html : "static";
                out.println(asset+"\t"+t.getCharacterId()+"\t"+detail+"\t"+b64(text));
            }
            if (tag instanceof DefineSpriteTag s) walk(s.getTags(),asset);
        }
    }
    public static void main(String[] args) throws Exception {
        try (PrintWriter w=new PrintWriter(Files.newBufferedWriter(Path.of(args[1])))) {
            out=w;
            try (var files=Files.list(Path.of(args[0]))) {
                for (Path p:files.sorted().toList()) {
                    if (!p.toString().endsWith(".gfx")) continue;
                    try(InputStream in=Files.newInputStream(p)) { SWF swf=new SWF(in,true);walk(swf.getTags(),p.getFileName().toString()); }
                }
            }
        }
    }
}
