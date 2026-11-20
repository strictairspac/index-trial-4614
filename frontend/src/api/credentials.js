import {api,post} from './client.js';
// 仅管理员；所有返回字段已在后端脱敏，前端不接触明文密码
export const credentials={
 status:()=>api('/credentials/status'),
 rotate:database_url=>post('/credentials/rotate',{database_url}),
 retire:()=>post('/credentials/retire',{})
};
