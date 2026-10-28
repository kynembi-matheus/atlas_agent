"""Agrupamento de apresentação; preserva as conversas próprias dos subagentes."""
from repositories.workspaces import Workspaces


def session_groups(store, limit=None):
    repo = Workspaces(store)
    runs = store.list_conversations()
    roots = {run.conversation_id: run for run in runs if not run.origin_conversation_id}
    origins = {run.origin_conversation_id: run for run in reversed(runs) if run.origin_conversation_id}
    groups = []
    for key in roots.keys() | origins.keys():
        root = roots.get(key)
        seed = root or origins[key]
        title = (root.title or root.prompt) if root else seed.context_snapshot.get('title') or 'Nova sessão'
        group = root.model_dump(mode='json') if root else {
            'id': None, 'conversation_id': key, 'title': title, 'prompt': '',
            'status': 'idle', 'created_at': seed.created_at,
        }
        group['title'] = title
        group['subagents'] = []
        latest = seed.created_at
        for index, profile in enumerate(repo.list_subagents(key)):
            run = store.get_run(profile['run_id']) if profile.get('run_id') else None
            group['subagents'].append({
                'id': profile['id'], 'name': profile['name'], 'status': run.status if run else profile['status'],
                'run_id': run.id if run else None, 'task': profile.get('task', ''),
                'color': 'teal' if index == 0 else 'violet',
            })
            if run:
                latest = max(latest, run.created_at)
        group['activity_at'] = latest
        groups.append(group)
    return sorted(groups, key=lambda item: (item['activity_at'], item['conversation_id']), reverse=True)[:limit]
