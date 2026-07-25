import os, re

src = r'C:\CODE_game-development\praxis\src'

print('=== Error handling patterns ===')
print()

# 1. bare except: pass
total_bare = 0
for root, dirs, files in os.walk(src):
    for f in files:
        if not f.endswith('.py'): continue
        fp = os.path.join(root, f)
        with open(fp, encoding='utf-8') as fh:
            content = fh.read()
        bare = len(re.findall(r'except\s+Exception:\s*pass', content))
        if bare:
            total_bare += bare
            rel = os.path.relpath(fp, src)
            print(f'  bare except:pass  {bare:2}x  {rel}')
print(f'  total bare except:pass: {total_bare}')
print()

# 2. {"success": False, "error": ...} returns  
total_ret = 0
for root, dirs, files in os.walk(src):
    for f in files:
        if not f.endswith('.py'): continue
        fp = os.path.join(root, f)
        with open(fp, encoding='utf-8') as fh:
            content = fh.read()
        ret = len(re.findall(r'\{"success"\s*:\s*False', content))
        if ret:
            total_ret += ret
            rel = os.path.relpath(fp, src)
            print(f'  return success=False  {ret:2}x  {rel}')
print(f'  total success=False returns: {total_ret}')
print()

# 3. raise statements
total_raise = 0
for root, dirs, files in os.walk(src):
    for f in files:
        if not f.endswith('.py'): continue
        fp = os.path.join(root, f)
        with open(fp, encoding='utf-8') as fh:
            content = fh.read()
        ras = len(re.findall(r'^\s*raise\s+', content, re.MULTILINE))
        if ras:
            total_raise += ras
print(f'  total raise statements: {total_raise}')
print()

# 4. Files with the most bare except: pass
print('=== Top 10 files with most except:pass ===')
hits = []
for root, dirs, files in os.walk(src):
    for f in files:
        if not f.endswith('.py'): continue
        fp = os.path.join(root, f)
        with open(fp, encoding='utf-8') as fh:
            content = fh.read()
        bare = len(re.findall(r'except\s+(\w+\s*)?:\s*pass', content))
        if bare:
            rel = os.path.relpath(fp, src)
            hits.append((bare, rel))
hits.sort(reverse=True)
for count, rel in hits[:10]:
    print(f'  {count:2}x  {rel}')
