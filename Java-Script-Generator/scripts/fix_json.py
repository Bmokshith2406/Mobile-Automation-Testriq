import json
import glob
import os

for path in glob.glob('fixtures/**/*.json', recursive=True):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    framework = os.path.basename(os.path.dirname(path))
    if framework in ['appium', 'cypress', 'playwright', 'selenium']:
        new_data = {}
        if 'test_case_id' in data: new_data['test_case_id'] = data['test_case_id']
        if 'description' in data: new_data['description'] = data['description']
        new_data['target_framework'] = framework
        if 'prerequisites' in data: new_data['prerequisites'] = data['prerequisites']
        if 'steps' in data: new_data['steps'] = data['steps']
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, indent=2)
            
print('Done!')
