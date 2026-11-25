"""Bounded startup preparation; no media playback or retry of playback here."""
import time
from .hmk_models import MediaError

class KodiStartup:
    def __init__(self, probe, launch, timeout=20, clock=time.monotonic, sleep=time.sleep, foreground=lambda:True):
        if type(timeout) not in (int,float) or not 3<=timeout<=30:
            raise ValueError('Kodi-Startwartezeit muss zwischen 3 und 30 Sekunden liegen.')
        self.probe,self.launch,self.timeout,self.clock,self.sleep=probe,launch,timeout,clock,sleep
        self.foreground=foreground

    def ensure(self, force_launch=False):
        started=self.clock()
        if self.probe() and not force_launch:
            return {'status':'already_ready','ms':round((self.clock()-started)*1000)}
        try:
            self.launch()
        except MediaError:
            raise
        except Exception:
            raise MediaError('Kodi konnte nicht geöffnet werden. Google-TV-Verbindung prüfen.') from None
        while self.clock()-started<self.timeout:
            if self.probe() and self.foreground():
                return {'status':'launched','ms':round((self.clock()-started)*1000)}
            self.sleep(min(1,max(0,self.timeout-(self.clock()-started))))
        raise MediaError('Kodi wurde angefordert, antwortet aber noch nicht. Fernseher und Kodi-Verbindung prüfen; es wurde nichts abgespielt.')