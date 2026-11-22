// Own action block appended after the original HUD frame-one actions.
var __zhOriginalShowPopups = ShowPopups;
ShowPopups = function(show)
{
   this.__zhOriginalShowPopups.apply(this,arguments);
   _root.AS_SetSubtitlePosition();
};

var __zhOriginalShowHud = ShowHud;
ShowHud = function(show)
{
   this.__zhOriginalShowHud.apply(this,arguments);
   _root.AS_SetSubtitlePosition();
};

var __zhOriginalAdjustForScreenDimensions = AdjustForScreenDimensions;
AdjustForScreenDimensions = function()
{
   this.__zhOriginalAdjustForScreenDimensions.apply(this,arguments);
   _root.AS_SetSubtitlePosition();
};
