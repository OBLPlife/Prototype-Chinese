// Inspect every AVM1 source block, including buttons and clip event handlers.
import java.io.*;
import java.nio.file.*;
import java.util.*;
import com.jpexs.decompiler.flash.SWF;
import com.jpexs.decompiler.flash.action.*;
import com.jpexs.decompiler.flash.action.swf4.ActionPush;
import com.jpexs.decompiler.flash.action.swf5.ActionConstantPool;
import com.jpexs.decompiler.flash.helpers.*;

public class AuditGfxScripts {
    static String b64(String s){return Base64.getEncoder().encodeToString(s.getBytes(java.nio.charset.StandardCharsets.UTF_8));}
    public static void main(String[] args)throws Exception {
        Path output=Path.of(args[1]);Files.createDirectories(output);
        int movies=0,scripts=0,strings=0;
        try(var rows=new PrintWriter(Files.newBufferedWriter(output.resolve("strings.tsv")));
            var files=Files.list(Path.of(args[0]))) {
            for(Path path:files.sorted().toList()) {
                if(!path.toString().endsWith(".gfx"))continue;
                SWF swf;try(var in=Files.newInputStream(path)){swf=new SWF(in,true);}
                Path folder=output.resolve(path.getFileName().toString());Files.createDirectories(folder);
                int block=0;
                for(var entry:swf.getASMs(false).entrySet()) {
                    var actions=entry.getValue().getActions();Set<String> values=new LinkedHashSet<>();
                    for(Action a:actions) {
                        if(a instanceof ActionConstantPool p)values.addAll(p.constantPool);
                        if(a instanceof ActionPush p)for(Object value:p.values)if(value instanceof String s)values.add(s);
                    }
                    for(String s:values){rows.println(path.getFileName()+"\t"+block+"\t"+b64(entry.getKey())+"\t"+b64(s));strings++;}
                    var writer=new HighlightedTextWriter(new CodeFormatting(),false);
                    entry.getValue().getActionScriptSource(writer,actions);
                    Files.writeString(folder.resolve(String.format("%04d.as",block)),"// "+entry.getKey()+"\n"+writer.toString());
                    scripts++;block++;
                }
                rows.flush();movies++;System.out.println(path.getFileName()+" scripts="+block);
            }
        }
        Files.writeString(output.resolve("counts.json"),"{\"movies\":"+movies+",\"scripts\":"+scripts+",\"literal_occurrences\":"+strings+",\"failed\":0}\n");
    }
}
