import importlib
import os
import shutil
import threading
from typing import TYPE_CHECKING, Any

from utils import json2py, get_resource_path, del_dir_tree

if TYPE_CHECKING:
    from hazedumper.config import Info as ConfigInfo
    from hazedumper.csgo import Info as CsgoInfo


class A:
    class Info:
        ...


class Config:
    _single_lock = threading.Lock()
    _instance = None

    config_info: "ConfigInfo"
    csgo_info: "CsgoInfo"

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._single_lock:
                if not cls._instance:
                    cls._instance = super(Config, cls).__new__(cls)
        return cls._instance

    def __init__(self, path: str = "hazedumper"):
        need_copy, real_path = get_resource_path(path)

        if need_copy:
            if os.path.isdir(path):
                del_dir_tree(path)
            shutil.copytree(os.path.join(os.getcwd(), real_path), path)

        self.path = path

        self.__load_json_configs()

    def __load_json_config(self, file):
        """加载json中的配置，并将其输出至 py 中"""
        if file.endswith(".json") and (not file.endswith(".min.json")):
            json2py(os.path.join(self.path, file))
            attr_name = file.rsplit(".", 1)[0]
            temp_module: Any = importlib.import_module(self.path + "." + attr_name)
            self.__dict__[f"{attr_name}_info"] = temp_module.Info

    def __load_json_configs(self):

        _, _, files = next(os.walk(self.path))
        for file in files:
            self.__load_json_config(file)
