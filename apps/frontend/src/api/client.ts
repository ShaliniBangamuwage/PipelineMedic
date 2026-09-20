const API=import.meta.env.VITE_API_BASE_URL||'/api';
let token=''; let refreshPromise:Promise<string>|null=null;
const unscoped=['/auth/','/organizations'];
export function setToken(value:string){token=value} export function getToken(){return token}
function isUnscoped(path:string){return unscoped.some(prefix=>path.startsWith(prefix))||path.startsWith('/invitations/')}
async function refresh(){if(!refreshPromise){refreshPromise=fetch(API+'/auth/refresh',{method:'POST',credentials:'include'}).then(async response=>{if(!response.ok)throw new Error('Session expired');const result=await response.json();token=result.access_token;return token}).finally(()=>{refreshPromise=null})}return refreshPromise}
export async function request(path:string,options:RequestInit={},retried=false){
	const protectedRequest=!isUnscoped(path)&&!path.startsWith('/auth/');
	if(!token&&protectedRequest&&!retried) await refresh();
	const headers=new Headers(options.headers);
	if(token)headers.set('Authorization',`Bearer ${token}`);
	const organizationId=localStorage.getItem('pipelinemedic.organization');
	if(organizationId&&protectedRequest)headers.set('X-Organization-ID',organizationId);
	const response=await fetch(API+path,{...options,headers,credentials:'include'});
	if(response.status===401&&!retried&&protectedRequest){
		try{await refresh();return request(path,options,true)}catch{token='';localStorage.removeItem('pipelinemedic.organization');sessionStorage.clear();sessionStorage.setItem('pipelinemedic.sessionMessage','Session expired. Please log in again.');const target=location.pathname+location.search+location.hash;if(!['/login','/register'].includes(location.pathname))sessionStorage.setItem('pipelinemedic.returnTo',target);location.href='/login';throw new Error('Session expired')}
	}
	if(!response.ok)throw new Error((await response.json().catch(()=>({}))).detail||'The API is unavailable');
	return response.json();
}
export function clearSession(){token='';localStorage.removeItem('pipelinemedic.organization');sessionStorage.clear()}
