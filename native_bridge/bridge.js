/* Transport only: all visible mobile screens are native Android views. */
'use strict';
let client='', lastLoginAck='', lastDelivery='';
function post(type,extra={}){window.parent.postMessage({isStreamlitMessage:true,type,...extra},'*')}
window.addEventListener('message',event=>{
  if(event.source!==window.parent)return;
  const message=event.data||{};
  if(message.type==='streamlit:render'){
    const args=message.args||{};
    client=String(args.client||'');
    if(!client)return;
    const response=args.response||null;
    // This interface has no file/system privileges. Android rejects stale clients.
    if(window.MandalTransport&&typeof window.MandalTransport.deliver==='function'){
      window.MandalTransport.deliver(JSON.stringify({protocol:3,client,data:args.data||{},response}));
    }
    if(response&&response.action==='login'&&response.delivery!==lastLoginAck){
      lastLoginAck=response.delivery;
      post('streamlit:setComponentValue',{value:{id:crypto.randomUUID(),action:'ack'},dataType:'json'});
    }
  }else if(message.mandalNativeRequest===true&&client&&message.client===client){
    const delivery=message.delivery;
    if(typeof delivery!=='string'||delivery===lastDelivery||!message.request)return;
    lastDelivery=delivery;
    post('streamlit:setComponentValue',{value:{id:delivery,action:'native_request',request:message.request},dataType:'json'});
  }
});
post('streamlit:componentReady',{apiVersion:1});
post('streamlit:setFrameHeight',{height:0});
