import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("OpenCodeBridge")


def run():
    logger.info("=== OpenCodeBridge 启动 ===")
    logger.info("Python: %s", sys.version)
    logger.info("Platform: %s", sys.platform)

    logger.info("创建 QApplication...")
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("OpenCodeBridge")
    logger.info("QApplication 创建成功")

    logger.info("创建 MainWindow...")
    from opencode_bridge.gui.main_window import MainWindow
    window = MainWindow()
    logger.info("MainWindow 创建成功")

    from PyQt6.QtCore import QTimer
    from PyQt6.QtGui import QGuiApplication

    # 居中显示
    screen = QGuiApplication.primaryScreen()
    if screen:
        geom = screen.availableGeometry()
        center = geom.center()
        frame = window.frameGeometry()
        frame.moveCenter(center)
        window.move(frame.topLeft())
        logger.info("屏幕可用区域: (%d, %d, %d, %d)", geom.x(), geom.y(), geom.width(), geom.height())
        logger.info("窗口居中到: (%d, %d)", frame.x(), frame.y())

    logger.info("显示窗口...")
    window.show()
    window.raise_()
    window.activateWindow()

    # 延迟再次尝试激活（窗口首次显示时可能被其他窗口遮挡）
    def reactivate():
        logger.info("延迟激活窗口")
        window.raise_()
        window.activateWindow()
    QTimer.singleShot(500, reactivate)

    logger.info("窗口可见性: %s, 位置: (%d, %d), 大小: (%d, %d)",
                 window.isVisible(), window.x(), window.y(),
                 window.width(), window.height())

    logger.info("进入事件循环")
    exit_code = app.exec()
    logger.info("事件循环结束, 退出码: %d", exit_code)
    sys.exit(exit_code)
