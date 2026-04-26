import os
from pathlib import Path

import aiofiles
from pydantic import json

from config.config import config_get


async def json_to_file(filename: str, json_data: dict) -> bool:
    """
    Asynchronously saves a dictionary to a JSON file in the 'data/output' directory.

    Args:
        filename (str): The name of the file (e.g., 'soko_menu').
        json_data (dict): Data to save.

    Returns:
        bool: True if successful, False otherwise.
    """
    data_dir = str(config_get('DATA_DIR') or 'data')
    output_dir = str(config_get('OUTPUT_DIR') or 'output')

    base_path = Path(data_dir) / output_dir
    base_path.mkdir(parents=True, exist_ok=True)

    try:
        os.makedirs(output_dir, exist_ok=True)

        if not filename.endswith('.json'):
            filename += '.json'

        file_path = base_path / filename

        async with aiofiles.open(str(file_path), mode='w', encoding='utf-8') as f:
            await f.write(json.dumps(json_data, ensure_ascii=False, indent=4))

        print(f"✅ Data successfully saved to {file_path}")
        return True
    except Exception as e:
        print(f"❌ Error saving to file: {e}")
        return False