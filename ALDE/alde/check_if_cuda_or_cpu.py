
# Datei: app.py (Qt6/PySide6 GUI – ready to run)
import os
import sys
import time
import traceback
from typing import Optional

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel, QMessageBox, QHBoxLayout

# WICHTIG: CUDA-Umgebung festlegen VOR import torch!
# Optional: Per Umgebungsvariable APP_CUDA_VISIBLE_DEVICES steuern (z.B. "0" oder "0,1")
preferred = os.environ.get("APP_CUDA_VISIBLE_DEVICES", '0')

from torch_init import init_torch_cuda, summarize_torch_environment, select_device
import torch_init

torch_init.init_torch_cuda('0')

# init_torch_cuda(preferred_gpus=preferred)

# Erst hier torch importieren – danach CUDA_VISIBLE_DEVICES NICHT mehr verändern.
try:
    import torch
except Exception as e:
    torch = None
    _import_error = e
else:
    _import_error = None


class TorchTestWorker(QThread):
    result = Signal(dict)
    failed = Signal(str)

    def __init__(self, device: str, parent=None):
        super().__init__(parent)
        self.device = device

    def run(self):
        try:
            start = time.perf_counter()
            if torch is None:
                raise RuntimeError("PyTorch konnte nicht importiert werden.")

            # Simpler GPU/CPU-Test-Workload
            dev = torch.device(self.device)
            a = torch.randn((4096, 4096), device=dev)
            b = torch.randn((4096, 4096), device=dev)
            c = a @ b
            # sync für faire Zeitmessung
            if dev.type == "cuda":
                torch.cuda.synchronize()

            elapsed = time.perf_counter() - start
            # Rückgabe: kleine Statistik
            self.result.emit({
                "device": self.device,
                "shape": list(c.shape),
                "dtype": str(c.dtype),
                "elapsed_sec": round(elapsed, 4),
            })
        except Exception as e:
            tb = traceback.format_exc()
            self.failed.emit(f"{type(e).__name__}: {e}\n{tb}")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyTorch CUDA Check")

        layout = QVBoxLayout(self)

        self.info_label = QLabel(self)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.info_label)

        btn_layout = QHBoxLayout()
        self.btn_test_cpu = QPushButton("Test auf CPU", self)
        self.btn_test_gpu = QPushButton("Test auf GPU (cuda:0)", self)
        btn_layout.addWidget(self.btn_test_cpu)
        btn_layout.addWidget(self.btn_test_gpu)
        layout.addLayout(btn_layout)

        self.status_label = QLabel(self)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status_label)

        self.worker: Optional[TorchTestWorker] = None

        self.btn_test_cpu.clicked.connect(lambda: self.start_test("cpu"))
        self.btn_test_gpu.clicked.connect(self.start_gpu_test)

        self.refresh_info()

    def refresh_info(self):
        if torch is None:
            self.info_label.setText(
                "PyTorch Import-Fehler:\n"
                f"{type(_import_error).__name__}: {_import_error}\n\n"
                "Lösung: Stellen Sie sicher, dass PyTorch installiert ist und die Version "
                "zu Ihrem Python/OS passt. Für CUDA-Unterstützung muss eine CUDA-fähige "
                "PyTorch-Build installiert sein und ein kompatibler NVIDIA-Treiber laufen."
            )
            self.btn_test_gpu.setEnabled(False)
            return

        info = summarize_torch_environment(torch)
        txt = [
            f"torch_version: {info.get('torch_version')}",
            f"compiled_for_cuda: {info.get('cuda_compiled_version')}",
            f"cuda_is_available: {info.get('cuda_is_available')}",
            f"device_count: {info.get('device_count')}",
            f"devices: {', '.join(info.get('devices', [])) or '-'}",
            f"cudnn_enabled: {info.get('cudnn_enabled')}",
        ]
        if "cuda_error" in info:
            txt.append(f"cuda_error: {info['cuda_error']}")
        if "devices_error" in info:
            txt.append(f"devices_error: {info['devices_error']}")

        self.info_label.setText("\n".join(txt))

        # Enable/Disable GPU-Button
        enable_gpu = bool(info.get("cuda_is_available")) and int(info.get("device_count", 0)) > 0
        self.btn_test_gpu.setEnabled(enable_gpu)

    def start_gpu_test(self):
        if torch is None:
            QMessageBox.critical(self, "Fehler", "PyTorch ist nicht verfügbar.")
            return
        device = select_device(torch, 0)
        self.start_test(device)

    def start_test(self, device: str):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Info", "Ein Test läuft bereits.")
            return
        self.status_label.setText(f"Starte Test auf {device} ...")
        self.worker = TorchTestWorker(device)
        self.worker.result.connect(self.on_test_result)
        self.worker.failed.connect(self.on_test_failed)
        self.worker.start()

    def on_test_result(self, data: dict):
        self.status_label.setText(
            f"OK auf {data['device']}: shape={data['shape']}, dtype={data['dtype']}, "
            f"elapsed={data['elapsed_sec']}s"
        )

    def on_test_failed(self, msg: str):
        self.status_label.setText("Fehler beim Test")
        QMessageBox.critical(self, "Test fehlgeschlagen", msg)


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.resize(700, 300)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

'''
Kurz­erklärung (was war falsch, was wurde gefixt):
- Ursache der Warnung: torch meldet häufig "CUDA initialization: CUDA unknown error ..." wenn die Umgebung nach Prozessstart geändert wurde, typischerweise durch nachträgliches Setzen/Ändern von CUDA_VISIBLE_DEVICES oder das Ändern NACH dem Import von torch. Intern setzt PyTorch dann die verfügbaren Geräte auf 0.
- Fix: CUDA_VISIBLE_DEVICES muss vor dem ersten Import von torch gesetzt werden. Das übernimmt init_torch_cuda() in torch_init.py. Danach darf die Variable nicht mehr geändert werden.
- Robustheit: Die GUI nutzt sichere Device-Auswahl, fällt ohne Ausnahme auf CPU zurück, zeigt eine klare Zusammenfassung der Torch/CUDA-Umgebung und erlaubt einen einfachen Rechen-Test auf CPU/GPU.
- Anwendung: Optional APP_CUDA_VISIBLE_DEVICES="0" vor dem Start setzen (z. B. APP_CUDA_VISIBLE_DEVICES=0 python app.py). Wenn CUDA nicht korrekt installiert/kompatibel ist (Treiber/CUDA-Build), läuft die App ohne Fehler auf CPU.

Drop-in Patch-Hinweis für bestehende Projekte:
- Bewege jedes Setzen von os.environ["CUDA_VISIBLE_DEVICES"] VOR den ersten import torch.
- Alternativ: Importiere zuerst torch_init.init_torch_cuda(...), dann erst torch.
- Entferne/verschiebe spätere Änderungen an CUDA_VISIBLE_DEVICES aus allen Modulen, die nach dem torch-Import ausgeführt werden.''' 