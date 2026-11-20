import {esc} from '../utils/html.js';
// 页面只渲染后端脱敏后的状态；连接串由管理员即时输入，提交后不落本地存储
export function credentialsPage(st){
 if(!st)return '<div class="empty"><h2>正在读取账号状态…</h2></div>';
 return `<div class="result-head"><div><span class="eyebrow">CREDENTIAL ROTATION / 两代账号</span><h2>数据库账号轮换</h2></div></div>
<div class="metrics">
 <div><small>当前生效世代</small><strong>#${st.active_generation}<em>${esc(st.active_account)}</em></strong></div>
 <div><small>待退役旧账号</small><strong>${st.previous_present?'#'+st.previous_generation:'无'}<em>${st.previous_present?esc(st.previous_account):'已清理'}</em></strong></div>
 <div><small>旧账号可否撤销</small><strong>${st.previous_present?(st.previous_revocable?'可撤':'不可撤'):'—'}<em>${st.previous_present?('在跑试验 '+(st.previous_running_experiments.length)+' · 未退连接 '+st.previous_open_connections):'无遗留'}</em></strong></div>
</div>
${st.previous_present&&!st.previous_revocable?`<div class="feedback">旧账号仍被在跑试验或未退出连接占用，需等试验清理完索引并保存成绩后才可撤。</div>`:''}
<div class="evidence"><section>
 <h3>轮换到新账号</h3>
 <p class="muted">提交后后端会先用新账号真实连库验权（登录 + 探测 telemetry 表）；验权不过则保留旧账号，状态不变。切换后新请求与新试验走新账号，在跑试验沿用旧账号直至完成。</p>
 <form id="credential-form">
  <label>新账号连接串（mysql+pymysql://user:password@host:3306/db）
   <input name="database_url" required minlength="10" maxlength="500" placeholder="mysql+pymysql://new_user:new_pass@db:3306/indextrial" autocomplete="off">
  </label>
  <button type="submit">验权并轮换</button>
 </form>
 <h3>退役旧账号</h3>
 <p class="muted">仅当旧试验全部清理、旧连接全部退出后可执行；否则返回冲突并保留旧账号。</p>
 <button id="credential-retire" ${st.previous_present&&st.previous_revocable?'':'disabled'}>退役并确认可撤</button>
</section><section>
 <h3>当前状态（已脱敏）</h3>
 <pre>${esc(JSON.stringify(st,null,2))}</pre>
 <p class="muted">版本 v${st.version}；最近轮换 ${esc(st.rotated_at||'—')}；最近退役 ${esc(st.retired_at||'—')}。服务中断恢复后继续使用已生效账号。</p>
</section></div>`;
}
