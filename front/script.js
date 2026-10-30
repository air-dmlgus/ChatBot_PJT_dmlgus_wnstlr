const API_BASE_URL = 'http://localhost:8000';
const chatWindow = document.querySelector('#chat-window');
const input = document.querySelector('#user-input');
const sendBtn = document.querySelector('#send-btn');
const welcome = document.querySelector('#welcome');
const uploadPanel = document.querySelector('#upload-panel');
const uploadStatus = document.querySelector('#upload-status');
let busy = false;
let answerMode = 'rag';
document.querySelectorAll('.mode').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('.mode').forEach(item => item.classList.toggle('active', item === button));
  answerMode = button.dataset.mode;
}));

function addMessage(text, role, source = '') {
  welcome?.remove();
  const row = document.createElement('div'); row.className = `message-row ${role}-row`;
  if (role === 'bot') { const avatar = document.createElement('div'); avatar.className = 'bot-avatar'; avatar.textContent = '🥑'; row.append(avatar); }
  const content = document.createElement('div');
  const bubble = document.createElement('div'); bubble.className = 'bubble'; bubble.textContent = text; content.append(bubble);
  if (source) { const meta = document.createElement('div'); meta.className = 'source-line'; meta.textContent = `✦ ${source}`; content.append(meta); }
  row.append(content); chatWindow.append(row); chatWindow.scrollTop = chatWindow.scrollHeight; return row;
}
function errorText(error) { return error?.message || '요청을 처리하지 못했어요. 서버 연결을 확인해주세요.'; }
async function sendMessage(prefill) {
  if (busy) return;
  const message = (prefill ?? input.value).trim(); if (!message) return;
  addMessage(message, 'user'); input.value = ''; resizeInput(); busy = true; sendBtn.disabled = true;
  const pending = addMessage('답변을 준비하고 있어요', 'bot'); pending.querySelector('.bubble').classList.add('typing');
  try {
    const endpoint = answerMode === 'chat' ? '/chat' : answerMode === 'search' ? '/search' : '/integrated-chat';
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message})});
    const data = await response.json(); if (!response.ok) throw new Error(data.detail || '서버 오류가 발생했어요.');
    pending.remove();
    const answer = answerMode === 'search' && data.results?.length ? `${data.answer}\n\n유사도: ${data.score ?? '—'}${data.source ? ` · 출처: ${data.source}` : ''}` : data.answer;
    const source = answerMode === 'rag' ? (data.rag_used ? `참고 문서 · ${data.source}` : '참고 문서 없음 · 일반 지식 답변') : answerMode === 'search' ? '벡터 유사도 검색 결과' : '일반 AI 답변';
    addMessage(answer || '답변을 받지 못했어요.', 'bot', source);
  } catch (error) { pending.remove(); addMessage(errorText(error), 'bot'); }
  finally { busy = false; sendBtn.disabled = false; input.focus(); }
}
function resizeInput(){input.style.height='auto';input.style.height=`${Math.min(input.scrollHeight,120)}px`;}
sendBtn.addEventListener('click', () => sendMessage());
input.addEventListener('input', resizeInput);
input.addEventListener('keydown', e => { if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();} });
document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click',()=>sendMessage(button.dataset.prompt)));
document.querySelector('#new-chat').addEventListener('click',()=>location.reload());
document.querySelector('#upload-toggle').addEventListener('click',()=>uploadPanel.classList.toggle('hidden'));
document.querySelector('#close-upload').addEventListener('click',()=>uploadPanel.classList.add('hidden'));

document.querySelector('#upload-form').addEventListener('submit', async e => {
  e.preventDefault(); const form=e.currentTarget, button=form.querySelector('.upload-submit');
  if(!form.querySelector('[name=file]').files.length)return;
  button.disabled=true; uploadStatus.className='loading'; uploadStatus.textContent='문서를 읽고 학습하는 중…';
  try { const response=await fetch(`${API_BASE_URL}/upload`,{method:'POST',body:new FormData(form)}); const data=await response.json(); if(!response.ok)throw new Error(data.detail||'업로드 실패');
    uploadStatus.className='success';uploadStatus.textContent=data.message||'문서 학습을 완료했어요.';form.reset();loadDocuments();
  } catch(err){uploadStatus.className='error';uploadStatus.textContent=errorText(err);} finally{button.disabled=false;}
});
async function loadDocuments(){
  const list=document.querySelector('#doc-list');
  try{const res=await fetch(`${API_BASE_URL}/documents`);if(!res.ok)throw new Error();const data=await res.json();list.replaceChildren();
    if(!data.documents?.length){const empty=document.createElement('div');empty.className='doc-loading';empty.textContent='아직 등록된 문서가 없어요';list.append(empty);return;}
    data.documents.forEach(doc=>{const row=document.createElement('div');row.className='doc-row';const icon=document.createElement('span');icon.className='doc-icon';icon.textContent='▤';const name=document.createElement('span');name.textContent=doc.source;row.append(icon,name);row.title=`${doc.chunks}개 문서 조각`;list.append(row);});
  }catch{list.replaceChildren();const note=document.createElement('div');note.className='doc-loading';note.textContent='서버 연결 후 문서를 표시해요';list.append(note);}
}
loadDocuments();
