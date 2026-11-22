// Own action block appended to popupHUD's original first frame (sprite 393).
// mActive becomes false one frame before hiding; keep our reservation until
// that actual hidden frame. ShowPopups(true) alone does not create a task.
var __zhSubtitleObstacle = false;
var __zhOriginalShowObjectivePopup = ShowObjectivePopup;
ShowObjectivePopup = function(titleMsg,msg)
{
   this.__zhOriginalShowObjectivePopup.apply(this,arguments);
   if(titleMsg != "" && msg != "") this.__zhSubtitleObstacle = true;
   _root.AS_SetSubtitlePosition();
};

var __zhOriginalObjectiveExit = OnExit;
OnExit = function()
{
   this.__zhSubtitleObstacle = false;
   this.__zhOriginalObjectiveExit.apply(this,arguments);
   _root.AS_SetSubtitlePosition();
};
