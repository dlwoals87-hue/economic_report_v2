from __future__ import annotations
from typing import Any

SKIP={'NO_PENDING_PPI_EVENT','ALREADY_PROCESSED'}
SUCCESS={'PROCESSED_AND_INDEXED','INDEX_ONLY_RESUMED'}

def build_notification(result: dict[str,Any], *, workflow_conclusion: str='success') -> dict[str,Any]:
    status=result.get('status') if workflow_conclusion=='success' else 'UPSTREAM_WORKFLOW_FAILURE'
    event_id=result.get('event_id') or 'UNKNOWN'
    if status in SKIP:
        return {'status':'NOTIFICATION_SKIPPED','upstream_status':status,'event_id':result.get('event_id'),'notification_action':'none','issue_created':False,'issue_updated':False,'issue_number':None,'external_ai_api_called':False,'cost':'free'}
    category='success' if status in SUCCESS else 'failure'
    title=f"[PPI Processing {'Success' if category=='success' else 'Failure'}] {event_id}"
    key=f"ppi-processing:{event_id}:{category}"
    body=f"<!-- {key} -->\nstatus: {status}\nevent_id: {event_id}\nreference_period: {result.get('reference_period')}\nprovider: {result.get('provider')}\nexternal_api_called: {result.get('external_api_called',False)}\nexternal_ai_api_called: false\ncost: {result.get('cost_mode','free')}\ncommit_paths: {result.get('commit_paths',[])}\nNot investment advice."
    return {'status':'NOTIFICATION_READY','upstream_status':status,'event_id':event_id,'category':category,'dedupe_key':key,'title':title,'body':body,'labels':['ppi-processing','automation',category],'external_ai_api_called':False,'cost':'free'}

def decide_issue_action(notification: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    if notification['status'] == 'NOTIFICATION_SKIPPED': return notification | {'notification_action':'none','issue_created':False,'issue_updated':False,'issue_number':None}
    marker=f"<!-- automation-key: {notification['dedupe_key']} -->"
    matches=[issue for issue in issues if marker in str(issue.get('body',''))]
    if len(matches)>1:return notification | {'status':'DUPLICATE_ISSUE_CONFLICT','notification_action':'none','issue_created':False,'issue_updated':False,'issue_number':None}
    body=marker+'\n'+notification['body']
    if not matches:return notification | {'notification_action':'created','issue_created':True,'issue_updated':False,'issue_number':None,'body':body}
    issue=matches[0]
    return notification | {'notification_action':'unchanged' if issue.get('body')==body else 'updated','issue_created':False,'issue_updated':issue.get('body')!=body,'issue_number':issue.get('number'),'body':body}
