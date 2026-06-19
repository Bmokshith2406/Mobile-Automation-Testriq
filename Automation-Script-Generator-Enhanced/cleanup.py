# Delete __pycache__ folders                                
>> Get-ChildItem -Path . -Recurse -Directory -Force -Filter "__pycache__" |                      
>> Remove-Item -Recurse -Force
>> 
>> # Delete compiled Python cache files
>> Get-ChildItem -Path . -Recurse -File -Force -Include *.pyc, *.pyo |
>> Remove-Item -Force
>> 
>> # Delete common Python tool caches
>> Get-ChildItem -Path . -Recurse -Directory -Force -Include ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox" |
>> Remove-Item -Recurse -Force
>> 
>> Write-Host "Python cache cleanup completed."