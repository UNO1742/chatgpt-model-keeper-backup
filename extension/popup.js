document.querySelector('#retry').onclick = async () => {
  try {
    const [tab] = await chrome.tabs.query({active:true,currentWindow:true});
    const result = await chrome.tabs.sendMessage(tab.id,{type:'retry'});
    document.querySelector('#result').textContent = result?.ok ? '已重新检测，结果显示在额度助理里。' : '请刷新 ChatGPT 页面。';
  } catch { document.querySelector('#result').textContent='请先打开并刷新 chatgpt.com。'; }
};
