// Static inspection only; invoke analyzeHeadless with -readOnly -noanalysis.
// @category PrototypeZh
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import java.io.PrintWriter;
import java.nio.file.*;
import java.util.*;

public class InspectEngine extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        DecompInterface dc = new DecompInterface();
        dc.openProgram(currentProgram);
        Set<Address> seen = new HashSet<>();
        try(PrintWriter out = new PrintWriter(Files.newBufferedWriter(Path.of(args[0])))) {
            for(int i=1;i<args.length;i++) {
                if(args[i].contains(":")) {
                    String[] range=args[i].split(":");
                    Address end=toAddr(range[1]);
                    for(Function f:currentProgram.getFunctionManager().getFunctions(toAddr(range[0]),true)) {
                        if(f.getEntryPoint().compareTo(end)>=0) break;
                        if(seen.add(f.getEntryPoint())) {
                            out.println("// FUNCTION " + f.getEntryPoint());
                            DecompileResults d=dc.decompileFunction(f,40,monitor);
                            out.println(d.decompileCompleted()?d.getDecompiledFunction().getC():d.getErrorMessage());
                        }
                    }
                    continue;
                }
                Address address = toAddr(args[i]);
                out.println("\n// TARGET " + address);
                List<Function> fs = new ArrayList<>();
                Function own = getFunctionContaining(address);
                if(own==null && currentProgram.getMemory().getBlock(address).isExecute()) {
                    // Read-only headless project: analysis additions are discarded on exit.
                    disassemble(address);
                    own=createFunction(address,null);
                }
                if(own!=null) fs.add(own);
                for(Reference r:getReferencesTo(address)) {
                    out.println("// REF " + r);
                    if(own==null) {
                        Function f = getFunctionContaining(r.getFromAddress());
                        if(f!=null) fs.add(f);
                    }
                }
                for(Function f:fs) if(seen.add(f.getEntryPoint())) {
                    out.println("// FUNCTION " + f.getEntryPoint());
                    DecompileResults d = dc.decompileFunction(f,40,monitor);
                    out.println(d.decompileCompleted()?d.getDecompiledFunction().getC():d.getErrorMessage());
                }
            }
        } finally { dc.dispose(); }
    }
}
