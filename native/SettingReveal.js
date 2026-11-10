// Bounded, on-demand lookup of a named setting in the already-open page.
function find(root,name) {
    var pending=[root],visited=0;
    while(pending.length && visited++<2048) {
        var item=pending.shift();
        if(item.objectName===name)return item;
        if(item.children)for(var i=0;i<item.children.length;i++)pending.push(item.children[i]);
    }
    return null;
}
function reveal(view,name) {
    var item=find(view,name);
    if(!item)return false;
    var flick=view.contentItem;
    if(flick && typeof flick.contentY!=="undefined" && flick.contentItem) {
        var point=item.mapToItem(flick.contentItem,0,0),height=flick.height;
        var next=flick.contentY;
        if(point.y<next+12)next=point.y-12;
        else if(point.y+item.height>next+height-12)next=point.y+item.height-height+12;
        flick.contentY=Math.max(0,Math.min(next,Math.max(0,flick.contentHeight-height)));
    }
    if(item.visible && item.enabled) {
        if(typeof item.focusSelection==="function")item.focusSelection();
        else if(typeof item.forceActiveFocus==="function")item.forceActiveFocus(Qt.TabFocusReason);
    }
    return true;
}
