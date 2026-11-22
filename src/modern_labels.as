// Text-only bridge for the existing original prototoggle control.
// No display mode operations, render state, timers, or per-screen references.
if(_global.prototoggle != undefined && !_global.prototoggle.prototype.__PrototypeZhLabels)
{
    _global.prototoggle.prototype.__PrototypeZhLabels = true;
    _global.prototoggle.prototype.__PrototypeZhSetLabel = _global.prototoggle.prototype.SetLabel;
    _global.prototoggle.prototype.__PrototypeZhAddElement = _global.prototoggle.prototype.AddElement;
    _global.prototoggle.prototype.SetLabel = function(label)
    {
        if(label == "Display Mode") label = "显示模式";
        return this.__PrototypeZhSetLabel(label);
    };
    _global.prototoggle.prototype.AddElement = function(label, value)
    {
        if(label == "Fullscreen") label = "全屏";
        else if(label == "Borderless") label = "无边框全屏";
        else if(label == "Windowed") label = "窗口";
        return this.__PrototypeZhAddElement(label, value);
    };
}
