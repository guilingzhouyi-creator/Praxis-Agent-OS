import ast, os, re

tools_dirs = [
    r'C:\CODE_game-development\praxis\src\tools\base',
    r'C:\CODE_game-development\praxis\src\tools\advanced',
    r'C:\CODE_game-development\praxis\src\tools\cell',
    r'C:\CODE_game-development\praxis\src\tools\special',
]

all_tool_names = []
for d in tools_dirs:
    for f in sorted(os.listdir(d)):
        if not f.endswith('.py') or f == '__init__.py':
            continue
        fp = os.path.join(d, f)
        with open(fp, encoding='utf-8') as fh:
            content = fh.read()
        names = re.findall(r'ToolSpec\(name="([^"]+)"', content)
        if names:
            print(f'{os.path.basename(d)}/{f[:-3]}:')
            for n in names:
                print(f'  - {n}')
            all_tool_names.extend(names)

print(f'\nTotal: {len(all_tool_names)} tools registered')
print()

# Check for specific keywords
keywords = [
    ('session_search / FTS5', ['session', 'fts', 'search_long', 'long_term']),
    ('spawn / delegation', ['spawn', 'delegat', 'subagent', 'scout_delegate']),
    ('skill management', ['skill']),
    ('browser', ['browser']),
    ('kanban / task board', ['kanban', 'task_board', 'board']),
]

for label, kws in keywords:
    matches = [n for n in all_tool_names for kw in kws if kw in n]
    print(f'{label}: {matches if matches else "NONE"}')
