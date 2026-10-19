(function(){
  function snap(label){
    var s=document.getElementById('scroller');
    var bar=document.getElementById('actionBar');
    var tc=document.querySelector('.el-tabs__content');
    var sr=s.getBoundingClientRect(), br=bar.getBoundingClientRect(), tr=tc.getBoundingClientRect();
    var clippedByMain=Math.max(0,Math.round(br.bottom-sr.bottom));
    var clippedByTabs=Math.max(0,Math.round(br.bottom-tr.bottom));
    var visible=Math.round(Math.min(br.bottom,sr.bottom)-Math.max(br.top,sr.top));
    return label+': scrollTop='+Math.round(s.scrollTop)+'/'+s.scrollHeight
      +' barH='+Math.round(br.height)
      +' barVisibleInMain='+visible+'px'
      +' clippedByMain='+clippedByMain+'px'
      +' clippedByTabsContent='+clippedByTabs+'px';
  }
  var s=document.getElementById('scroller');
  var out=[];
  s.scrollTop=Math.round(s.scrollHeight*0.45); out.push(snap('mid45'));
  s.scrollTop=Math.round(s.scrollHeight*0.70); out.push(snap('mid70'));
  s.scrollTop=s.scrollHeight; out.push(snap('maxScroll'));
  return 'MARKER '+out.join(' || ');
})()
