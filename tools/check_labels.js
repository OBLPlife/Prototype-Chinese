// Runs the decompiled compiler output against control-contract fixtures.
// It does not launch the game or automate any UI.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const labelSource=fs.readFileSync(process.argv[2],'utf8');
const modernSource=fs.readFileSync(process.argv[3],'utf8');
let cases=0;
for(const ordering of ['zh-first','modern-first','no-modern']) {
  function Toggle(){this.mElements=[];this.value=0;}
  Toggle.prototype.SetLabel=function(label){this.label=label;return 'original-label-return';};
  Toggle.prototype.AddElement=function(label,value){this.mElements.push({label,value});return 'original-element-return';};
  Toggle.prototype.SetSelectedByValue=function(v){this.value=v;};
  Toggle.prototype.GetSelectedValue=function(){return this.value;};
  Toggle.prototype.MouseOverHandler=function(){};
  Toggle.prototype.duplicateMovieClip=function(){return new Toggle();};
  function Options(movie,dbName,dbType,label,data,profileIndex,count,delayed,published){
    Object.assign(this,{mMovie:movie,mDBName:dbName,mLabel:label,mData:data,mGetPublishedValue:published});
  }
  Options.DBTYPE_INT=0;
  Options.prototype.Initialize=function(){this.mMovie.SetLabel(this.mLabel);this.mData.forEach(x=>this.mMovie.AddElement(x.mLabel,x.mValue));this.mMovie.SetSelectedByValue(this.GetGameDBValue());};
  let requested=0,applied=0,commits=0,nativeSaves=0;
  const resolution=new Toggle(),options=[{mDBName:'SettingVideoResolution'}];
  const c={_global:{prototoggle:Toggle,PLATFORM:1,RAD_WIN32:1},
    mcVideoOverlay:{tglResolution:resolution,getNextHighestDepth(){return 10;}},
    optionscontainer:Options,mVideoOptions:options,mOptions:options,SaveSettings(){nativeSaves++;},
    flash:{external:{ExternalInterface:{call(name,v){
      if(name==='PM_GetDisplayMode')return requested;
      if(name==='PM_GetAppliedDisplayMode')return applied;
      if(name==='PM_SetDisplayMode'){requested=v;return true;}
      if(name==='PM_CommitDisplayMode'){commits++;return true;}
      throw Error(name);
    }}}}};
  vm.createContext(c);
  if(ordering==='zh-first'||ordering==='no-modern')vm.runInContext(labelSource,c);
  if(ordering!=='no-modern')vm.runInContext(modernSource,c);
  if(ordering==='modern-first')vm.runInContext(labelSource,c);
  // Repeated library initialization must not stack wrappers or retain old screens.
  const set=Toggle.prototype.SetLabel,add=Toggle.prototype.AddElement;
  for(let i=0;i<20;i++)vm.runInContext(labelSource,c);
  assert.strictEqual(Toggle.prototype.SetLabel,set);assert.strictEqual(Toggle.prototype.AddElement,add);
  if(ordering!=='no-modern'){
    const mode=options[0];
    for(let repeat=0;repeat<100;repeat++){
      mode.Initialize();assert.equal(mode.mMovie.label,'显示模式');
      assert.deepStrictEqual(Array.from(mode.mMovie.mElements,x=>[x.label,x.value]),[['全屏',0],['无边框全屏',1],['窗口',2]]);
    }
    mode.mMovie.value=2;mode.WriteValueToGameDB();assert.equal(requested,2);assert.equal(applied,0);
    mode.WriteValueToGameDB(0);assert.equal(requested,0);assert.equal(commits,0);
    mode.WriteValueToGameDB(1);applied=1;c.SaveSettings();assert.equal(commits,1);assert.equal(nativeSaves,1);
  }
  const unchanged=new Toggle();assert.equal(unchanged.SetLabel('分辨率'),'original-label-return');
  assert.equal(unchanged.AddElement('3440x1440',27),'original-element-return');
  assert.deepStrictEqual(unchanged.mElements,[{label:'3440x1440',value:27}]);
  assert.equal(unchanged.label,'分辨率');cases++;
}
console.log(JSON.stringify({passed:true,cases,compiledOutputTested:true,labels:['显示模式','全屏','无边框全屏','窗口'],modeValuesPreserved:true,
  originalReturnValuesPreserved:true,repeatInitializationNoStacking:true,gameExecuted:false},null,2));
