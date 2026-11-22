// Encode the same contours with the game's native DefineCompactedFont format.
// 2048 nominal units preserve every point on the original 1/2048-em grid.
import java.io.*;
import java.nio.file.*;
import java.util.*;
import com.jpexs.decompiler.flash.SWF;
import com.jpexs.decompiler.flash.tags.*;
import com.jpexs.decompiler.flash.tags.gfx.DefineCompactedFont;
import com.jpexs.decompiler.flash.types.*;
import com.jpexs.decompiler.flash.types.gfx.*;
import com.jpexs.decompiler.flash.types.shaperecords.*;
import com.jpexs.helpers.MemoryInputStream;

public class CompactFonts {

    // Native compact contours may reference an earlier inline edge block in
    // the same font byte buffer. Keep move points and every edge unchanged.
    static final class EdgeBytes {
        final byte[] bytes;final int hash;
        EdgeBytes(byte[] bytes){this.bytes=bytes;this.hash=Arrays.hashCode(bytes);}
        @Override public int hashCode(){return hash;}
        @Override public boolean equals(Object other){return other instanceof EdgeBytes b && Arrays.equals(bytes,b.bytes);}
    }
    static final class SharedContourWriter {
        final Map<EdgeBytes,Integer> offsets=new HashMap<>();
        int base,references;long saved;
        final class SharedContour extends ContourType {
            SharedContour(ContourType source){moveToX=source.moveToX;moveToY=source.moveToY;edges=source.edges;}
            @Override public void write(GFxOutputStream out)throws IOException {
                out.writeSI15(moveToX);out.writeSI15(moveToY);
                ByteArrayOutputStream block=new ByteArrayOutputStream();
                GFxOutputStream edgeOut=new GFxOutputStream(block);
                edgeOut.writeUI30(edges.length<<1);
                for(EdgeType edge:edges)edge.write(edgeOut);
                byte[] bytes=block.toByteArray();EdgeBytes key=new EdgeBytes(bytes);
                Integer prior=offsets.get(key);
                if(prior!=null){
                    if(prior<0 || prior >= (1<<29))throw new IOException("Compact contour reference overflow");
                    ByteArrayOutputStream encoded=new ByteArrayOutputStream();
                    new GFxOutputStream(encoded).writeUI30((prior<<1)|1);
                    byte[] reference=encoded.toByteArray();
                    if(reference.length<bytes.length){out.write(reference);references++;saved+=bytes.length-reference.length;return;}
                }
                // Targets are inline count+edge blocks, never another reference.
                offsets.putIfAbsent(key,Math.toIntExact(base+out.getPos()));
                out.write(bytes);
            }
        }
        byte[] write(FontType font)throws IOException {
            offsets.clear();references=0;saved=0;
            // FontType.write starts a fresh stream: name+NUL, five UI16s,
            // glyph count UI32, glyph-data size UI32, then the glyph buffer.
            base=font.fontName.getBytes().length+19;
            List<ContourType[]> originals=new ArrayList<>();
            try {
                for(GlyphType glyph:font.glyphs){
                    originals.add(glyph.contours);
                    ContourType[] shared=new ContourType[glyph.contours.length];
                    for(int i=0;i<shared.length;i++)shared[i]=new SharedContour(glyph.contours[i]);
                    glyph.contours=shared;
                }
                ByteArrayOutputStream buffer=new ByteArrayOutputStream();
                font.write(new GFxOutputStream(buffer));return buffer.toByteArray();
            } finally {
                for(int i=0;i<originals.size();i++)font.glyphs.get(i).contours=originals.get(i);
                offsets.clear();
            }
        }
    }
    // JPEXS 26.4's C11 reader sign-extends one packed bit of control-Y.
    // C13 is equivalent and avoids that tooling bug without changing points.
    static class CheckedEdge extends EdgeType {
        CheckedEdge(EdgeType source){data=source.data;}
        @Override public void write(GFxOutputStream out)throws IOException {
            SHAPERECORD r=toSHAPERECORD();
            if(r instanceof CurvedEdgeRecord q) {
                int[] values={q.controlDeltaX,q.controlDeltaY,q.anchorDeltaX,q.anchorDeltaY};
                boolean nine=true,eleven=true;
                for(int v:values){nine&=v>=-256&&v<=255;eleven&=v>=-1024&&v<=1023;}
                if(!nine&&eleven) {
                    long bits=12;for(int i=0;i<4;i++)bits|=((long)values[i]&8191)<<(4+13*i);
                    for(int i=0;i<7;i++)out.write((int)(bits>>>(8*i))&255);
                    return;
                }
            }
            super.write(out);
        }
    }
    static int exact(int n,int d) {
        if(n%d!=0)throw new IllegalStateException("Non-exact font coordinate "+n+" / "+d);
        return n/d;
    }
    static List<String> geometry(SHAPE shape,int divisor) {
        List<String> out=new ArrayList<>();
        String move="M 0 0";
        for(SHAPERECORD r:shape.shapeRecords) {
            if(r instanceof StyleChangeRecord x && x.stateMoveTo)
                move="M "+exact(x.moveDeltaX,divisor)+" "+exact(x.moveDeltaY,divisor);
            else if(r instanceof StraightEdgeRecord x && (x.deltaX!=0 || x.deltaY!=0)) {
                if(move!=null){out.add(move);move=null;}
                out.add("L "+exact(x.deltaX,divisor)+" "+exact(x.deltaY,divisor));
            } else if(r instanceof CurvedEdgeRecord x) {
                if(move!=null){out.add(move);move=null;}
                out.add("Q "+exact(x.controlDeltaX,divisor)+" "+exact(x.controlDeltaY,divisor)+" "+exact(x.anchorDeltaX,divisor)+" "+exact(x.anchorDeltaY,divisor));
            }
        }
        return out;
    }
    static void include(int[] bounds,int axis,long value) {
        if(value<Integer.MIN_VALUE || value>Integer.MAX_VALUE)throw new IllegalStateException("Font bound overflow");
        bounds[axis]=Math.min(bounds[axis],(int)value);
        bounds[axis+2]=Math.max(bounds[axis+2],(int)value);
    }
    static void curveBounds(int[] bounds,int axis,int start,int control,int end) {
        include(bounds,axis,start);include(bounds,axis,end);
        long delta=(long)start-control,denominator=(long)start-2L*control+end;
        // The quadratic derivative vanishes at t=(start-control)/(start-2*control+end).
        // Include an interior extremum with outward integer rounding, using exact
        // rational arithmetic so a negative coordinate cannot be rounded inward.
        if((denominator>0 && delta>0 && delta<denominator) ||
           (denominator<0 && delta<0 && delta>denominator)) {
            long numerator=(long)start*denominator-delta*delta;
            include(bounds,axis,Math.floorDiv(numerator,denominator));
            include(bounds,axis,-Math.floorDiv(-numerator,denominator));
        }
    }
    static int[] outlineBounds(SHAPE shape,int divisor) {
        int[] bounds={Integer.MAX_VALUE,Integer.MAX_VALUE,Integer.MIN_VALUE,Integer.MIN_VALUE};
        int x=0,y=0;
        for(SHAPERECORD r:shape.shapeRecords) {
            if(r instanceof StyleChangeRecord s && s.stateMoveTo) {
                x=exact(s.moveDeltaX,divisor);y=exact(s.moveDeltaY,divisor);
            } else if(r instanceof StraightEdgeRecord s && (s.deltaX!=0 || s.deltaY!=0)) {
                include(bounds,0,x);include(bounds,1,y);
                x+=exact(s.deltaX,divisor);y+=exact(s.deltaY,divisor);
                include(bounds,0,x);include(bounds,1,y);
            } else if(r instanceof CurvedEdgeRecord q) {
                int cx=x+exact(q.controlDeltaX,divisor),cy=y+exact(q.controlDeltaY,divisor);
                int ex=cx+exact(q.anchorDeltaX,divisor),ey=cy+exact(q.anchorDeltaY,divisor);
                curveBounds(bounds,0,x,cx,ex);curveBounds(bounds,1,y,cy,ey);
                x=ex;y=ey;
            }
        }
        return bounds[0]==Integer.MAX_VALUE?new int[]{0,0,0,0}:bounds;
    }
    public static void main(String[] args)throws Exception {
        SWF swf;try(InputStream in=Files.newInputStream(Path.of(args[0]))){swf=new SWF(in,true);}
        Path folder=Path.of(args[1]);Files.createDirectories(folder);
        int total=0,bytes=0,updatedBounds=0,sharedContours=0;
        long savedEdgeBytes=0;
        for(Tag tag:swf.getTags()) {
            if(!(tag instanceof DefineFont3Tag original))continue;
            if(!Set.of("PrototypeBodyPC","PrototypeSubtitle","PrototypeTitlePC").contains(original.fontName.replace("\0","")))continue;
            FontType f=new FontType();f.fontName=original.fontName.replace("\0","");f.nominalSize=2048;
            f.flags=(original.fontFlagsItalic?FontType.FF_Italic:0)|(original.fontFlagsBold?FontType.FF_Bold:0);
            // Compact header line metrics are in normalized 1024 units; glyph
            // contours, advances and kerning use nominalSize units.
            f.ascent=exact(original.fontAscent,20);f.descent=exact(original.fontDescent,20);f.leading=exact(original.fontLeading,20);
            for(int i=0;i<original.codeTable.size();i++) {
                SHAPE source=original.glyphShapeTable.get(i);
                List<String> expected=geometry(source,10);
                GlyphType glyph=new GlyphType(source.resize(0.1).shapeRecords);
                for(ContourType contour:glyph.contours)
                    for(int j=0;j<contour.edges.length;j++)contour.edges[j]=new CheckedEdge(contour.edges[j]);
                // DefineFont3's stored layout rectangles are placeholders in the
                // original fonts. The classic reader discards them and computes
                // bounds from the outline. DefineCompactedFont trusts its stored
                // bounds for glyph-cache sizing: copying zero rectangles here
                // makes large glyphs overflow the original 48-pixel cache slot.
                glyph.boundingBox=outlineBounds(source,10);
                RECT b=original.fontBoundsTable.get(i);
                if(!Arrays.equals(glyph.boundingBox,new int[]{exact(b.Xmin,10),exact(b.Ymin,10),exact(b.Xmax,10),exact(b.Ymax,10)}))updatedBounds++;
                for(int v:glyph.boundingBox)if(v < -16384 || v>16383)throw new IllegalStateException("Compact bounds overflow");
                if(!expected.isEmpty() && Arrays.equals(glyph.boundingBox,new int[]{0,0,0,0}))throw new IllegalStateException("Nonempty glyph has zero bounds "+i);
                if(!expected.equals(geometry(glyph.toSHAPE(),1)))throw new IllegalStateException("Contour changed "+i+" before="+expected+" after="+geometry(glyph.toSHAPE(),1));
                if(!Arrays.equals(glyph.boundingBox,outlineBounds(glyph.toSHAPE(),1)))throw new IllegalStateException("Outline bounds mismatch "+i);
                f.glyphs.add(glyph);
                f.glyphInfo.add(new GlyphInfoType(original.codeTable.get(i),exact(original.fontAdvanceTable.get(i),10),0));
            }
            for(KERNINGRECORD k:original.fontKerningTable)
                f.kerning.add(new KerningPairType(k.fontKerningCode1,k.fontKerningCode2,exact(k.fontKerningAdjustment,10)));
            SharedContourWriter shared=new SharedContourWriter();
            byte[] raw=shared.write(f);
            FontType decoded=new FontType(new GFxInputStream(new MemoryInputStream(raw)));
            if(decoded.glyphs.size()!=f.glyphs.size() || decoded.nominalSize!=f.nominalSize || decoded.ascent!=f.ascent || decoded.descent!=f.descent || decoded.leading!=f.leading || !decoded.fontName.equals(f.fontName) || decoded.flags!=f.flags)throw new IllegalStateException("Header roundtrip");
            for(int i=0;i<f.glyphs.size();i++) {
                if(!geometry(decoded.glyphs.get(i).toSHAPE(),1).equals(geometry(original.glyphShapeTable.get(i),10)))throw new IllegalStateException("Decoded geometry changed "+i+" expected="+geometry(original.glyphShapeTable.get(i),10)+" actual="+geometry(decoded.glyphs.get(i).toSHAPE(),1));
                if(!Arrays.equals(decoded.glyphs.get(i).boundingBox,f.glyphs.get(i).boundingBox) || decoded.glyphInfo.get(i).glyphCode!=f.glyphInfo.get(i).glyphCode || decoded.glyphInfo.get(i).advanceX!=f.glyphInfo.get(i).advanceX)throw new IllegalStateException("Decoded glyph metrics changed");
                if(!Arrays.equals(decoded.glyphs.get(i).boundingBox,outlineBounds(decoded.glyphs.get(i).toSHAPE(),1)))throw new IllegalStateException("Decoded bounds do not enclose outline "+i);
            }
            if(decoded.kerning.size()!=f.kerning.size())throw new IllegalStateException("Kerning count");
            for(int i=0;i<f.kerning.size();i++) {
                KerningPairType a=f.kerning.get(i),b=decoded.kerning.get(i);
                if(a.char1!=b.char1 || a.char2!=b.char2 || a.advance!=b.advance)throw new IllegalStateException("Kerning changed");
            }
            ByteArrayOutputStream payload=new ByteArrayOutputStream();
            payload.write(original.fontID&255);payload.write(original.fontID>>8);payload.write(raw);
            Files.write(folder.resolve("font-"+original.fontID+".bin"),payload.toByteArray());
            total+=f.glyphs.size();bytes+=raw.length;
            sharedContours+=shared.references;savedEdgeBytes+=shared.saved;
            System.out.println(f.fontName+" glyphs="+f.glyphs.size()+" bytes="+raw.length+" geometry/advances/kerning exact; bounds derived from outlines; shared_contours="+shared.references+" saved_edge_bytes="+shared.saved);
        }
        if(total==0)throw new IllegalStateException("No fonts");
        Files.writeString(folder.resolve("validation.json"),"{\"passed\":true,\"native_tag\":1005,\"nominal_size\":2048,\"glyphs\":"+total+",\"bytes\":"+bytes+",\"outlines_exact\":true,\"metrics_exact\":true,\"kerning_exact\":true,\"bounds_from_outlines\":true,\"updated_bounds\":"+updatedBounds+",\"contours_losslessly_shared\":true,\"shared_contours\":"+sharedContours+",\"saved_edge_bytes\":"+savedEdgeBytes+"}\n");
    }
}
