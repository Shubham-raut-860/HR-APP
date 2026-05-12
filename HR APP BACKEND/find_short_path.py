import os
import subprocess

def get_short_path_name(long_name):
    try:
        # Use cmd /c dir /x to find short name
        parent = os.path.dirname(long_name)
        basename = os.path.basename(long_name)
        result = subprocess.check_output(f'cmd /c "dir /x \"{parent}\""', shell=True).decode('utf-8')
        for line in result.splitlines():
            if basename in line:
                parts = line.split()
                # Short name is usually the 4th or 5th column if it exists
                # Example: 10/26/2023  11:00 AM    <DIR>          HRAPP~1      HR APP
                for part in parts:
                    if '~1' in part or '~2' in part:
                        return os.path.join(parent, part)
    except Exception as e:
        print(f"Error: {e}")
    return long_name

print(get_short_path_name(r"d:\shubham\HR APP"))
