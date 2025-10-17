import flet as ft
import httpx
import hashlib
import asyncio
import sqlite3
from datetime import datetime

# --- 常量配置 ---
API_BASE_URL = 'https://v3-api.china-qzxy.cn'
LOGIN_URL = f'{API_BASE_URL}/user/login'
BALANCE_URL = f'{API_BASE_URL}/account/wallet'
START_WATER_URL = f'{API_BASE_URL}/order/tcpDevice/downRate/rateOrder'
STOP_WATER_URL = f'{API_BASE_URL}/order/tcpDevice/closeOrder'
SN_CODE = 'C47F0E0BD0C0'  # 固定设备SN码
DB_FILE = "water_app.db"  # 数据库文件名


class WaterControlApp:
    def __init__(self, page: ft.Page):
        """应用初始化"""
        self.page = page
        self.login_data = None
        self._db_init()
        self._setup_page()

        # --- UI控件定义 ---
        self.phone_input = ft.TextField(label="手机号", border_color="grey")
        self.password_input = ft.TextField(label="密码", password=True, can_reveal_password=True, border_color="grey")
        self.login_button = ft.FilledButton(text="登 录", icon="login", on_click=self.handle_login, width=200,
                                            height=45)
        self.login_progress = ft.ProgressRing(visible=False, width=24, height=24, stroke_width=3)

        self.balance_amount_text = ft.Text("¥ --.--", size=36, weight=ft.FontWeight.BOLD)
        self.refresh_button = ft.IconButton(icon="refresh_rounded", on_click=self.update_balance, tooltip="刷新余额")
        self.start_button = ft.FilledButton(text="开启水阀", icon="play_arrow_rounded", on_click=self.start_water,
                                            width=140, height=50)
        self.stop_button = ft.FilledButton(text="关闭水阀", icon="stop_rounded", on_click=self.stop_water, width=140,
                                           height=50, style=ft.ButtonStyle(bgcolor="red_700"))
        self.logout_button = ft.IconButton(icon="logout", on_click=self.handle_logout, tooltip="退出登录")

        # --- 视图构建 ---
        # 默认显示登录页，启动后会检查凭证并切换
        self.view_switcher = ft.AnimatedSwitcher(
            content=self._build_login_view(),
            transition=ft.AnimatedSwitcherTransition.FADE,
            duration=300,
        )
        self.page.add(self.view_switcher)

    async def post_init(self):
        """在页面构建后执行的异步初始化任务"""
        await self._load_credentials_and_auto_login()

    def _db_init(self):
        """初始化数据库连接并创建表"""
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS credentials (
                    id INTEGER PRIMARY KEY,
                    telephone TEXT NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL,
                    login_code TEXT NOT NULL,
                    account_id INTEGER NOT NULL,
                    project_id INTEGER NOT NULL,
                    last_login TEXT NOT NULL
                )
            ''')
            conn.commit()

    def _save_credentials(self):
        """将登录凭证保存到数据库"""
        if not self.login_data: return
        user, account = self.login_data, self.login_data.get('userAccount', {})
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO credentials (telephone, user_id, login_code, account_id, project_id, last_login) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    user.get('telephone'),
                    user.get('userId'),
                    user.get('loginCode'),
                    account.get('accountId'),
                    account.get('projectId'),
                    datetime.now().isoformat()
                )
            )
            conn.commit()

    def _clear_credentials(self):
        """清除数据库中的所有凭证"""
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM credentials")
            conn.commit()

    async def _load_credentials_and_auto_login(self):
        """从数据库加载凭证并尝试自动登录"""
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.row_factory = sqlite3.Row  # 允许通过列名访问数据
            res = cursor.execute("SELECT * FROM credentials ORDER BY last_login DESC LIMIT 1").fetchone()

        if res:
            # 构建一个与API返回结构相似的login_data字典
            self.login_data = {
                "telephone": res["telephone"],
                "userId": res["user_id"],
                "loginCode": res["login_code"],
                "userAccount": {
                    "accountId": res["account_id"],
                    "projectId": res["project_id"]
                }
            }
            # 切换到主界面
            self.view_switcher.content = self._build_controls_view()
            self.page.update()
            # 验证凭证有效性
            await self.update_balance(on_startup=True)
        else:
            # 数据库为空，什么都不做，停留在登录页
            pass

    def _setup_page(self):
        """配置页面基础属性"""
        self.page.title = "校园水控 Pro"
        self.page.vertical_alignment = ft.MainAxisAlignment.CENTER
        self.page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.window_width = 400
        self.page.window_height = 550

    def _build_login_view(self) -> ft.Container:
        """构建登录界面的UI布局"""
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(name="water_drop_rounded", size=48, color="blue_500"),
                    ft.Text("校园水控", size=28, weight=ft.FontWeight.BOLD),
                    ft.Divider(height=20, color="transparent"),
                    self.phone_input,
                    self.password_input,
                    ft.Container(height=10),
                    ft.Row([self.login_button, self.login_progress], alignment=ft.MainAxisAlignment.CENTER,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=15,
            ), padding=ft.padding.symmetric(horizontal=30),
        )

    def _build_controls_view(self) -> ft.Container:
        """构建操作界面的UI布局"""
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row([ft.Text("当前余额", color="grey_600"), self.logout_button],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([self.balance_amount_text, self.refresh_button], alignment=ft.MainAxisAlignment.CENTER,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Divider(height=30),
                    ft.Text("水阀控制", size=18, weight=ft.FontWeight.W_500),
                    ft.Container(height=10),
                    ft.Row([self.start_button, self.stop_button], alignment=ft.MainAxisAlignment.SPACE_AROUND),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
            ), padding=ft.padding.all(20),
        )

    async def _toggle_ui_lock(self, locked: bool, from_login=False):
        """锁定或解锁所有交互控件"""
        self.login_button.disabled = locked
        self.start_button.disabled = locked
        self.stop_button.disabled = locked
        self.refresh_button.disabled = locked
        self.logout_button.disabled = locked
        self.login_progress.visible = locked and from_login
        self.page.update()

    async def _show_snackbar(self, message: str, color: str):
        """显示底部通知栏"""
        self.page.snack_bar = ft.SnackBar(ft.Text(message), bgcolor=color)
        self.page.snack_bar.open = True
        self.page.update()

    async def handle_login(self, e):
        """处理登录按钮点击事件"""
        phone, password = self.phone_input.value, self.password_input.value
        if not all([phone, password]):
            await self._show_snackbar("手机号和密码不能为空", "orange_700")
            return

        await self._toggle_ui_lock(True, from_login=True)

        try:
            md5_hash = hashlib.md5(password.encode('utf-8')).hexdigest()
            final_password = md5_hash[-10:].upper()
            form_data = {'password': final_password, 'phoneSystem': 'ios', 'telephone': phone, 'type': '0',
                         'version': '6.5.19'}

            async with httpx.AsyncClient() as client:
                response = await client.post(LOGIN_URL, data=form_data)
                response.raise_for_status()
                result = response.json()

            if not result.get("success"): raise Exception(result.get("errorMessage", "登录凭据无效"))

            self.login_data = result['data']
            self._save_credentials()  # 保存凭证到数据库
            await self._show_snackbar("登录成功！", "green_700")

            self.view_switcher.content = self._build_controls_view()
            self.page.update()
            await self.update_balance()

        except Exception as err:
            await self._show_snackbar(f"登录失败: {err}", "red_700")
            await self._toggle_ui_lock(False)

    async def handle_logout(self, e=None):
        """处理退出登录事件"""
        self._clear_credentials()
        self.login_data = None
        self.view_switcher.content = self._build_login_view()
        await self._show_snackbar("您已退出登录", "blue_grey_600")
        self.page.update()

    async def update_balance(self, e=None, on_startup=False):
        """更新余额，并在启动时验证凭证"""
        if not self.login_data: return
        await self._toggle_ui_lock(True)
        if not on_startup: await self._show_snackbar("正在刷新余额...", "blue_grey_600")

        try:
            user, account = self.login_data, self.login_data['userAccount']
            params = {'accountId': account['accountId'], 'loginCode': user['loginCode'], 'userId': user['userId'],
                      'projectId': account['projectId'], 'telephone': user['telephone'], 'phoneSystem': 'ios',
                      'version': '6.5.19', 'telPhone': user['telephone']}

            async with httpx.AsyncClient() as client:
                response = await client.get(BALANCE_URL, params=params)
                response.raise_for_status()
                result = response.json()

            if not result.get("success"): raise Exception(result.get("errorMessage", "未知错误"))

            self.balance_amount_text.value = f"¥ {result['data']['money']}"
            if not on_startup: await self._show_snackbar("余额已更新！", "green_700")

        except Exception as err:
            if on_startup:  # 如果是启动时验证失败，则自动登出
                await self._show_snackbar("凭证已失效，请重新登录", "red_700")
                await self.handle_logout()
                return  # 提前返回，不再执行finally中的解锁
            else:
                await self._show_snackbar(f"刷新余额失败: {err}", "red_700")
        finally:
            if self.login_data:  # 检查是否已登出
                await self._toggle_ui_lock(False)

    # ... 开水和关水的函数保持不变 ...
    async def start_water(self, e):
        """开启水阀"""
        if not self.login_data: return
        await self._toggle_ui_lock(True)
        await self._show_snackbar("正在发送开水指令...", "blue_grey_600")

        try:
            user, account = self.login_data, self.login_data['userAccount']
            form_data = {'accountId': account['accountId'], 'loginCode': user['loginCode'], 'userId': user['userId'],
                         'telephone': user['telephone'], 'phoneSystem': 'ios', 'projectId': 30, 'snCode': SN_CODE,
                         'telPhone': user['telephone'], 'version': '6.5.19', 'xfModel': '0'}
            headers = {'Config-Project': '30'}

            async with httpx.AsyncClient() as client:
                response = await client.post(START_WATER_URL, data=form_data, headers=headers)
                response.raise_for_status()
                result = response.json()

            if result.get("success"):
                await self._show_snackbar("操作成功，水阀已开启！", "green_700")
            elif result.get("errorCode") == 307:
                await self._show_snackbar("提示：设备已在您的账号下使用中。", "blue_600")
            else:
                raise Exception(result.get("errorMessage", "未知错误"))

            await asyncio.sleep(1.5)
            await self.update_balance()

        except Exception as err:
            await self._show_snackbar(f"开水失败: {err}", "red_700")
            await self._toggle_ui_lock(False)

    async def stop_water(self, e):
        """关闭水阀"""
        if not self.login_data: return
        await self._toggle_ui_lock(True)

        try:
            await self._show_snackbar("步骤1/2: 正在获取订单号...", "blue_grey_600")
            user, account = self.login_data, self.login_data['userAccount']
            form_data = {'accountId': account['accountId'], 'loginCode': user['loginCode'], 'userId': user['userId'],
                         'telephone': user['telephone'], 'phoneSystem': 'ios', 'projectId': 30, 'snCode': SN_CODE,
                         'telPhone': user['telephone'], 'version': '6.5.19', 'xfModel': '0'}
            headers = {'Config-Project': '30'}

            async with httpx.AsyncClient() as client:
                response = await client.post(START_WATER_URL, data=form_data, headers=headers)
                response.raise_for_status()
                get_order_result = response.json()

            if get_order_result.get("errorCode") != 307:
                raise Exception(get_order_result.get("errorMessage") or "获取订单号失败，水阀可能未开启")

            order_no = get_order_result['data']['orderNo']
            await self._show_snackbar(f"步骤2/2: 成功获取订单，正在关水...", "blue_grey_600")

            close_form = {'accountId': account['accountId'], 'loginCode': user['loginCode'], 'userId': user['userId'],
                          'orderNo': order_no, 'phoneSystem': 'ios', 'projectId': 30, 'snCode': SN_CODE,
                          'version': '6.5.19'}

            async with httpx.AsyncClient() as client:
                response = await client.post(STOP_WATER_URL, data=close_form, headers=headers)
                response.raise_for_status()
                close_result = response.json()

            if not close_result.get("success"):
                raise Exception(close_result.get("errorMessage", "关水指令失败"))

            await self._show_snackbar("操作成功，水阀已关闭！", "green_700")
            await asyncio.sleep(1.5)
            await self.update_balance()

        except Exception as err:
            await self._show_snackbar(f"关水失败: {err}", "red_700")
        finally:
            if self.login_data:
                await self._toggle_ui_lock(False)


# Flet应用的异步入口点
async def main(page: ft.Page):
    app = WaterControlApp(page)
    await app.post_init()  # 执行异步的初始化任务


# 主程序启动
if __name__ == "__main__":
    ft.app(target=main)