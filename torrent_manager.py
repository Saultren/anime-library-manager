import os
import asyncio
import logging
import pickle
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass
import libtorrent as lt

@dataclass
class TorrentStatus:
    """Текущий статус загрузки"""
    info_hash: str
    name: str
    state: str
    progress: float
    download_speed: int
    uploaded: int
    total_downloaded: int
    total_size: int
    num_peers: int
    num_seeds: int
    is_finished: bool
    save_path: str
    error: Optional[str] = None

class TorrentManager:
    """Управление торрент-загрузками через libtorrent (Потокобезопасный + Resume)"""
    
    def __init__(self, save_path: Path, loop: Optional[asyncio.AbstractEventLoop] = None):
        self.save_path = Path(save_path).expanduser().resolve()
        self.save_path.mkdir(parents=True, exist_ok=True)
        self.loop = loop or asyncio.get_running_loop()
        
        # Пути для сохранения состояния
        self.state_dir = self.save_path.parent / ".torrent_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.resume_file = self.state_dir / "resume_data"
        self.session_file = self.state_dir / "session_state"
        
        # Инициализация сессии (будет выполнена в потоке)
        self.session: Optional[lt.session] = None
        self._active_downloads: Dict[str, lt.torrent_handle] = {}
        self._shutdown_event = asyncio.Event()
        self._autosave_task: Optional[asyncio.Task] = None
        
        logging.info(f"TorrentManager инициализирован: {self.save_path}")

    async def start(self):
        """Асинхронный запуск сессии в отдельном потоке"""
        try:
            # Запускаем инициализацию в потоке
            self.session = await asyncio.to_thread(self._create_session)
            
            # Восстанавливаем состояние
            await self._load_session_state()
            
            # Запускаем автосохранение
            self._autosave_task = asyncio.create_task(self._autosave_loop())
            
            logging.info("TorrentManager запущен успешно")
        except Exception as e:
            logging.error(f"Ошибка запуска TorrentManager: {e}")
            # Попытка запуска в безопасном режиме (без DHT/PEX если порт занят)
            logging.warning("Попытка запуска в безопасном режиме...")
            self.session = await asyncio.to_thread(self._create_session_safe)
            self._autosave_task = asyncio.create_task(self._autosave_loop())

    def _create_session(self) -> lt.session:
        """Создание сессии (вызывается в потоке)"""
        session = lt.session({'listen_interfaces': '0.0.0.0:6881'})
        settings = {
            'user_agent': 'AnimeLibrary/1.0',
            'announce_to_all_trackers': True,
            'announce_to_all_tiers': True,
            'connections_limit': 100,
            'upload_rate_limit': 0,
            'download_rate_limit': 0,
            'stop_tracker_timeout': 5,
            'enable_dht': True,
            'enable_lsd': True,
        }
        session.apply_settings(settings)
        return session

    def _create_session_safe(self) -> lt.session:
        """Безопасное создание сессии (случайный порт)"""
        import random
        port = random.randint(10000, 20000)
        session = lt.session({'listen_interfaces': f'0.0.0.0:{port}'})
        settings = {
            'user_agent': 'AnimeLibrary/1.0',
            'stop_tracker_timeout': 5,
            'pex': False,
            'lsd': False,
            'announce_to_all_trackers': True,
            'connections_limit': 50,
        }
        session.apply_settings(settings)
        return session

    async def _load_session_state(self):
        """Восстановление сессии и загрузок из файлов"""
        if not self.session:
            return

        try:
            if self.resume_file.exists():
                logging.info("Загрузка resume-данных...")
                data = await asyncio.to_thread(lambda: self.resume_file.read_bytes())
                resume_data = pickle.loads(data)
                
                for info_hash, params in resume_data.items():
                    try:
                        handle = await asyncio.to_thread(self.session.add_torrent, params)
                        self._active_downloads[info_hash] = handle
                        logging.info(f"Восстановлен торрент: {info_hash}")
                    except Exception as e:
                        logging.warning(f"Не удалось восстановить {info_hash}: {e}")
            else:
                logging.info("Resume-данные не найдены, начинаем с чистого листа")
                
        except Exception as e:
            logging.error(f"Ошибка восстановления сессии: {e}")

    async def _autosave_loop(self):
        """Фоновый цикл автосохранения каждые 30 секунд"""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(30)
                await self._save_state()
                logging.debug("Автосохранение состояния выполнено")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Ошибка автосохранения: {e}")

    async def _save_state(self):
        """Сохранение текущего состояния сессии и загрузок"""
        if not self.session:
            return

        try:
            resume_data = {}
            handles = await asyncio.to_thread(self.session.get_torrents)
            
            for handle in handles:
                if handle.is_valid():
                    try:
                        info = await asyncio.to_thread(handle.torrent_file)
                        if info:
                            params = {
                                'ti': info,
                                'save_path': str(handle.save_path()),
                                'flags': handle.flags(),
                            }
                            resume_data[str(info.info_hash())] = params
                    except Exception as e:
                        logging.warning(f"Не удалось получить resume для торрента: {e}")

            if resume_data:
                await asyncio.to_thread(lambda: self.resume_file.write_bytes(pickle.dumps(resume_data)))
            
            session_state = await asyncio.to_thread(self.session.save_state)

            encoded_state = await asyncio.to_thread(lambda: lt.bencode(session_state))
            await asyncio.to_thread(lambda: self.session_file.write_bytes(encoded_state))
            
        except Exception as e:
            logging.error(f"Критическая ошибка сохранения состояния: {e}")

    async def add_torrent(self, torrent_file: Path, release_name: str) -> str:
        """Добавить .torrent файл в сессию (Асинхронно)"""
        if not self.session:
            raise RuntimeError("Сессия не инициализирована")

        try:
            torrent_data = await asyncio.to_thread(lambda: torrent_file.read_bytes())
            info = await asyncio.to_thread(lambda: lt.torrent_info(lt.bdecode(torrent_data)))
            info_hash = str(info.info_hash())
            
            if info_hash in self._active_downloads:
                handle = self._active_downloads[info_hash]
                if handle.is_valid():
                    logging.info(f"Торрент уже активен: {info_hash}")
                    return info_hash
            
            release_save_path = self.save_path / release_name
            release_save_path.mkdir(parents=True, exist_ok=True)

            params = {
                'ti': info,
                'save_path': str(release_save_path),
                'storage_mode': lt.storage_mode_t.storage_mode_sparse,
            }
            
            handle = await asyncio.to_thread(self.session.add_torrent, params)
            await asyncio.to_thread(handle.set_sequential_download, True)
            
            self._active_downloads[info_hash] = handle
            logging.info(f"Добавлен торрент: {info_hash} → {release_save_path}")
            
            await self._save_state()
            
            return info_hash
            
        except Exception as e:
            logging.error(f"Ошибка добавления торрента: {e}")
            raise

    async def get_status(self, info_hash: str) -> Optional[TorrentStatus]:
        """Получить текущий статус загрузки (Асинхронно)"""
        if info_hash not in self._active_downloads:
            return None
            
        handle = self._active_downloads[info_hash]
        if not handle.is_valid():
            return None

        status = await asyncio.to_thread(handle.status)
        
        state_map = {
            lt.torrent_status.checking_resume_data: "checking",
            lt.torrent_status.checking_files: "checking",
            lt.torrent_status.downloading_metadata: "downloading_meta",
            lt.torrent_status.downloading: "downloading",
            lt.torrent_status.finished: "finished",
            lt.torrent_status.seeding: "seeding",
            lt.torrent_status.paused: "paused",
        }
        state = state_map.get(status.state, "unknown")
        
        error_msg = status.error if status.error else None
        
        return TorrentStatus(
            info_hash=info_hash,
            name=status.name if handle.has_metadata() else "Загрузка метаданных...",
            state=state,
            progress=status.progress,
            download_speed=status.download_rate,
            uploaded=status.total_upload,
            total_downloaded=status.total_done,
            total_size=status.total_wanted,
            num_peers=status.num_peers,
            num_seeds=status.num_seeds,
            is_finished=status.is_finished,
            save_path=handle.save_path(),
            error=error_msg
        )

    async def pause_download(self, info_hash: str):
        """Пауза загрузки"""
        if info_hash in self._active_downloads:
            handle = self._active_downloads[info_hash]
            if handle.is_valid():
                await asyncio.to_thread(handle.pause)
                logging.info(f"Пауза: {info_hash}")
                await self._save_state()

    async def resume_download(self, info_hash: str):
        """Возобновить загрузку"""
        if info_hash in self._active_downloads:
            handle = self._active_downloads[info_hash]
            if handle.is_valid():
                await asyncio.to_thread(handle.resume)
                logging.info(f"Возобновлено: {info_hash}")

    async def remove_download(self, info_hash: str, delete_files: bool = False):
        """Удалить загрузку из сессии"""
        if info_hash not in self._active_downloads:
            return
            
        handle = self._active_downloads.pop(info_hash)
        if not handle.is_valid():
            return

        if delete_files:
            try:
                save_path = Path(handle.save_path())
                if save_path.exists():
                    import shutil
                    await asyncio.to_thread(lambda: shutil.rmtree(save_path))
                    logging.info(f"Удалены файлы: {save_path}")
            except Exception as e:
                logging.error(f"Ошибка удаления файлов: {e}")
        
        await asyncio.to_thread(self.session.remove_torrent, handle)
        logging.info(f"Удален торрент: {info_hash}")
        await self._save_state()

    async def get_all_statuses(self) -> List[TorrentStatus]:
        """Получить статус всех активных загрузок"""
        statuses = []
        for ih in list(self._active_downloads.keys()):
            status = await self.get_status(ih)
            if status:
                statuses.append(status)
        return statuses

    async def shutdown(self):
        """Корректное завершение работы"""
        logging.info("Остановка TorrentManager...")
        
        self._shutdown_event.set()
        if self._autosave_task:
            self._autosave_task.cancel()
            try:
                await self._autosave_task
            except asyncio.CancelledError:
                pass
        
        await self._save_state()
        
        if self.session:
            handles = await asyncio.to_thread(self.session.get_torrents)
            for handle in handles:
                if handle.is_valid():
                    await asyncio.to_thread(handle.pause)
            
            await asyncio.to_thread(self.session.pause)
            logging.info("TorrentManager остановлен")
