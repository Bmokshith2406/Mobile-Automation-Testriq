import os
import sys
import re

service_path = 'app/services/report_service.py'
with open(service_path, 'r', encoding='utf-8') as f:
    content = f.read()

# We need to extract everything between HTML_TEMPLATE = f""" and """
start_match = re.search(r'HTML_TEMPLATE\s*=\s*(f?)"""', content)
if start_match:
    start_idx = start_match.end()
    end_idx = content.find('"""', start_idx)
    
    template = content[start_idx:end_idx]
    if template.startswith('\n'):
        template = template[1:]
    
    os.makedirs('app/templates', exist_ok=True)
    with open('app/templates/legacy_report.html', 'w', encoding='utf-8') as f:
        f.write(template)
        
    print('Legacy template extracted.')
else:
    print('HTML_TEMPLATE not found!')
