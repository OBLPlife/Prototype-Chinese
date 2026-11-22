// Own action block appended after the original main timeline actions.
// All coordinates below are in the original main root's logical space.
function AS_SetSubtitlePosition()
{
   var clip = _global.gSubtitles;
   if(clip == undefined || clip.subtitleText == undefined) return;
   clip._x = _global.gScreenInfo.mOrigStageWidth / 2;
   if(!clip._visible) return;

   var text = clip.subtitleText;
   // Keep its native font, width, word wrapping and HTML paragraph alignment.
   // Auto-height makes the entire concurrent subtitle block measurable.
   if(text.autoSize != "left") text.autoSize = "left";
   if(text.scroll != 1) text.scroll = 1;

   var bottom = _global.gScreenInfo.mEffectiveScreenVMax;
   var hud = _root.mcAnchor;
   var popup = hud.popupHUD;
   if(popup != undefined && popup.__zhSubtitleObstacle && popup._visible &&
      hud._visible && !hud.mHudHidden && hud._alpha > 0)
   {
      // Reserve the task's vertical band even while its intro moves text
      // horizontally. The subtitle must not slide into the entering message.
      // Each of these original one-frame MovieClips contains only its text
      // field. Use the native MovieClip API, not an assumed TextField method.
      var titleBounds = popup.mcTitle.getBounds(_root);
      var messageBounds = popup.mcMessage.getBounds(_root);
      bottom = Math.min(bottom,Math.min(titleBounds.yMin,messageBounds.yMin) - 12);
   }

   // mcSubtitles is a direct, unscaled child of the original main root.
   // Reset before measuring so repeated updates cannot accumulate an offset.
   clip._y = 0;
   // Original mcSubtitles (sprite 6) likewise contains only subtitleText.
   var bounds = clip.getBounds(_root);
   clip._y = bottom - bounds.yMax;
}

var __zhOriginalSubtitleShow = AS_SubtitleShow;
AS_SubtitleShow = function(enable)
{
   _root.__zhOriginalSubtitleShow.apply(this,arguments);
   if(enable) _root.AS_SetSubtitlePosition();
};
