import {workloads,candidates,experiments} from '../api/business.js';
import {credentials} from '../api/credentials.js';
export const store={workloads:[],candidates:[],experiments:[],user:null,credentialStatus:null};
export async function refresh(){[store.workloads,store.candidates,store.experiments]=await Promise.all([workloads.list(),candidates.list(),experiments.list()]);}
export async function refreshCredentials(){if(store.user?.role==='admin')store.credentialStatus=await credentials.status();}
