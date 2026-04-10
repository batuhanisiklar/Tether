import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QDialog
from desktop_app.config import AppMeta
from desktop_app.database.db_client import DbClient

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(AppMeta.NAME)
    app.setApplicationVersion(AppMeta.VERSION)

    db = DbClient()
    if not db.init_schema():
        import logging
        logging.getLogger(__name__).warning("DB schema init başarısız")

    from desktop_app.ui.login_window import LoginWindow
    login = LoginWindow(db)
    if login.exec() != QDialog.DialogCode.Accepted:
        db.close()
        sys.exit(0)

    from desktop_app.ui.app_window import MainWindow
    window = MainWindow(db, backend_api=login.shared_backend_api)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
