import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput, Select
import sqlite3
import random
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

# تحميل التوكن من ملف .env


# إنشاء البوت
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# الاتصال بقاعدة البيانات
conn = sqlite3.connect('bank.db')
c = conn.cursor()

# إنشاء جدول المستخدمين إذا لم يكن موجودًا
c.execute('''CREATE TABLE IF NOT EXISTS users
             (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 100, last_daily TEXT)''')

# إنشاء جدول المتجر إذا لم يكن موجودًا
c.execute('''CREATE TABLE IF NOT EXISTS shop
             (item_id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT, price INTEGER, description TEXT)''')

# إنشاء جدول القروض إذا لم يكن موجودًا
c.execute('''CREATE TABLE IF NOT EXISTS loans
             (user_id INTEGER, amount INTEGER, interest_rate FLOAT, due_date TEXT)''')

# التحقق من وجود العمود description وإضافته إذا لم يكن موجودًا
c.execute("PRAGMA table_info(shop)")
columns = c.fetchall()
column_names = [column[1] for column in columns]

if 'description' not in column_names:
    c.execute("ALTER TABLE shop ADD COLUMN description TEXT")
    conn.commit()

conn.commit()

# رسوم التحويل (5%)
TRANSFER_FEE_RATE = 0.05

# معرف روم المتجر (Shop Room)
SHOP_ROOM_ID = 123456789012345678  # استبدل هذا بمعرف الروم الفعلي

# واجهة إدخال رقم المحفظة والمبلغ
class TransferMoneyModal(Modal, title="تحويل الأموال"):
    wallet_id = TextInput(label="رقم المحفظة", placeholder="أدخل رقم المحفظة هنا...")
    amount = TextInput(label="المبلغ", placeholder="أدخل المبلغ هنا...")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            wallet_id = int(self.wallet_id.value)
            amount = int(self.amount.value)

            # حساب الرسوم
            fee = int(amount * TRANSFER_FEE_RATE)
            total_deduct = amount + fee

            # التحقق من وجود المحفظة
            c.execute("SELECT user_id FROM users WHERE user_id = ?", (wallet_id,))
            receiver = c.fetchone()
            if not receiver:
                await interaction.response.send_message("رقم المحفظة غير صحيح!", ephemeral=True)
                return

            # التحقق من الرصيد
            c.execute("SELECT balance FROM users WHERE user_id = ?", (interaction.user.id,))
            balance = c.fetchone()[0]
            if balance < total_deduct:
                await interaction.response.send_message(f"رصيدك غير كافي! تحتاج إلى {total_deduct} سونك (بما في ذلك الرسوم).", ephemeral=True)
                return

            # التحويل مع الرسوم
            c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (total_deduct, interaction.user.id))
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, wallet_id))
            conn.commit()

            # إرسال تنبيه للمستخدم المستلم
            receiver_user = await bot.fetch_user(wallet_id)
            await receiver_user.send(f"لقد استلمت {amount} سونك من {interaction.user.name}!")

            await interaction.response.send_message(
                f"تم تحويل {amount} سونك إلى المحفظة رقم {wallet_id} مع رسوم تحويل بقيمة {fee} سونك.",
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message("الرجاء إدخال أرقام صحيحة!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"حدث خطأ: {e}", ephemeral=True)

# واجهة إدخال تفاصيل المنتج
class AddProductModal(Modal, title="نشر منتج جديد"):
    item_name = TextInput(label="اسم المنتج", placeholder="أدخل اسم المنتج هنا...")
    price = TextInput(label="سعر المنتج", placeholder="أدخل سعر المنتج هنا...")
    description = TextInput(label="وصف المنتج", placeholder="أدخل وصف المنتج هنا...", style=discord.TextStyle.long)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            item_name = self.item_name.value
            price = int(self.price.value)
            description = self.description.value

            # إضافة المنتج إلى المتجر
            c.execute("INSERT INTO shop (item_name, price, description) VALUES (?, ?, ?)",
                      (item_name, price, description))
            conn.commit()

            await interaction.response.send_message(f"تمت إضافة المنتج '{item_name}' بنجاح!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("الرجاء إدخال سعر صحيح!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"حدث خطأ: {e}", ephemeral=True)

# واجهة المستخدم الرئيسية
class BankUI(View):
    def __init__(self):
        super().__init__(timeout=None)  # عدم إنهاء الواجهة تلقائيًا

    @discord.ui.button(label="رصيدي", style=discord.ButtonStyle.primary, emoji="💰")
    async def check_balance(self, interaction: discord.Interaction, button: Button):
        user_id = interaction.user.id
        c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance = c.fetchone()
        if balance:
            await interaction.response.send_message(f"رصيدك الحالي: {balance[0]} سونك.", ephemeral=True)
        else:
            await interaction.response.send_message("ليس لديك محفظة! استخدم زر 'إنشاء محفظة'.", ephemeral=True)

    @discord.ui.button(label="مكافأة يومية", style=discord.ButtonStyle.success, emoji="🎁")
    async def daily_reward(self, interaction: discord.Interaction, button: Button):
        user_id = interaction.user.id
        c.execute("SELECT last_daily FROM users WHERE user_id = ?", (user_id,))
        last_daily = c.fetchone()[0]

        if last_daily and datetime.now() < datetime.fromisoformat(last_daily) + timedelta(days=1):
            await interaction.response.send_message("لقد استلمت مكافأتك اليومية بالفعل!", ephemeral=True)
            return

        reward = random.randint(50, 150)
        c.execute("UPDATE users SET balance = balance + ?, last_daily = ? WHERE user_id = ?",
                  (reward, datetime.now().isoformat(), user_id))
        conn.commit()

        await interaction.response.send_message(f"لقد استلمت {reward} سونك كمكافأة يومية!", ephemeral=True)

    @discord.ui.button(label="تحويل الأموال", style=discord.ButtonStyle.secondary, emoji="💸")
    async def send_money(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(TransferMoneyModal())

    @discord.ui.button(label="إنشاء محفظة", style=discord.ButtonStyle.green, emoji="🆕")
    async def create_wallet(self, interaction: discord.Interaction, button: Button):
        user_id = interaction.user.id
        c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        wallet = c.fetchone()

        if wallet:
            await interaction.response.send_message(f"لديك محفظة بالفعل!\nرقم المحفظة: {user_id}\nرصيدك الحالي: {wallet[0]} سونك.", ephemeral=True)
        else:
            c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
            conn.commit()
            await interaction.response.send_message(f"تم إنشاء محفظة لك!\nرقم المحفظة: {user_id}\nرصيدك الحالي: 100 سونك.", ephemeral=True)

    @discord.ui.button(label="المتجر", style=discord.ButtonStyle.blurple, emoji="🛒")
    async def open_shop(self, interaction: discord.Interaction, button: Button):
        c.execute("SELECT item_name, price, description FROM shop")
        items = c.fetchall()
        if not items:
            await interaction.response.send_message("المتجر فارغ حاليًا.", ephemeral=True)
            return

        select = Select(placeholder="اختر عنصرًا للشراء", options=[
            discord.SelectOption(label=f"{item[0]} - {item[1]} سونك", value=str(item[0])) for item in items
        ])

        async def select_callback(interaction: discord.Interaction):
            item_name = select.values[0]
            c.execute("SELECT price, description FROM shop WHERE item_name = ?", (item_name,))
            item = c.fetchone()
            if not item:
                await interaction.response.send_message("العنصر غير موجود في المتجر.", ephemeral=True)
                return

            price, description = item
            c.execute("SELECT balance FROM users WHERE user_id = ?", (interaction.user.id,))
            balance = c.fetchone()[0]
            if balance < price:
                await interaction.response.send_message("رصيدك غير كافي لشراء هذا العنصر.", ephemeral=True)
                return

            # خصم المبلغ من رصيد المستخدم
            c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, interaction.user.id))
            conn.commit()

            # إرسال تفاصيل الفاتورة إلى المستخدم في الرسائل الخاصة
            try:
                await interaction.user.send(
                    f"**فاتورة الشراء**\n"
                    f"العنصر: {item_name}\n"
                    f"السعر: {price} سونك\n"
                    f"الوصف: {description}\n"
                    f"تم خصم {price} سونك من رصيدك."
                )
            except discord.Forbidden:
                await interaction.response.send_message("تعذر إرسال الرسالة الخاصة. يرجى التأكد من أنك تسمح برسائل الدايركت.", ephemeral=True)
                return

            # إرسال إشعار بشراء المنتج في روم المتجر
            shop_room = bot.get_channel(SHOP_ROOM_ID)
            if shop_room:
                await shop_room.send(
                    f"تم شراء العنصر '{item_name}' بواسطة {interaction.user.mention}!\n"
                    f"السعر: {price} سونك."
                )

            await interaction.response.send_message(f"تم شراء العنصر '{item_name}' بسعر {price} سونك!", ephemeral=True)

        select.callback = select_callback
        view = View()
        view.add_item(select)
        await interaction.response.send_message("اختر عنصرًا للشراء:", view=view, ephemeral=True)

    @discord.ui.button(label="طلب قرض", style=discord.ButtonStyle.gray, emoji="💳")
    async def request_loan(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(RequestLoanModal())

    @discord.ui.button(label="سداد قرض", style=discord.ButtonStyle.red, emoji="💵")
    async def repay_loan(self, interaction: discord.Interaction, button: Button):
        user_id = interaction.user.id
        c.execute("SELECT amount, interest_rate FROM loans WHERE user_id = ?", (user_id,))
        loan = c.fetchone()
        if not loan:
            await interaction.response.send_message("ليس لديك أي قروض.", ephemeral=True)
            return

        amount, interest_rate = loan
        total_amount = int(amount * (1 + interest_rate))

        c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance = c.fetchone()[0]
        if balance < total_amount:
            await interaction.response.send_message(f"رصيدك غير كافي! تحتاج إلى {total_amount} سونك.", ephemeral=True)
            return

        # سداد القرض
        c.execute("DELETE FROM loans WHERE user_id = ?", (user_id,))
        c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (total_amount, user_id))
        conn.commit()

        await interaction.response.send_message(f"تم سداد القرض بنجاح! تم خصم {total_amount} سونك.", ephemeral=True)

# واجهة إدخال مبلغ القرض
class RequestLoanModal(Modal, title="طلب قرض"):
    amount = TextInput(label="المبلغ", placeholder="أدخل المبلغ هنا...")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value)
            user_id = interaction.user.id
            interest_rate = 0.1  # فائدة 10%
            due_date = (datetime.now() + timedelta(days=30)).isoformat()

            c.execute("INSERT INTO loans (user_id, amount, interest_rate, due_date) VALUES (?, ?, ?, ?)",
                      (user_id, amount, interest_rate, due_date))
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            conn.commit()

            await interaction.response.send_message(
                f"تمت الموافقة على قرض بقيمة {amount} سونك بفائدة 10%. يجب السداد قبل {due_date}.",
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message("الرجاء إدخال مبلغ صحيح!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"حدث خطأ: {e}", ephemeral=True)

# أمر لفتح واجهة المستخدم
@bot.command(name="bank")
async def open_bank_ui(ctx):
    view = BankUI()
    await ctx.send("**واجهة البنك**\nاختر الخيار الذي تريده:", view=view)

# أمر لنشر منتج جديد (للاستخدام من قبل الأدمن فقط)
@bot.command(name="add_product")
async def add_product(ctx):
    # التحقق من وجود الرتبة المطلوبة
    required_role = "إدارة المتجر"  # يمكنك تغييرها إلى اسم الرتبة التي تريدها
    if required_role not in [role.name for role in ctx.author.roles]:
        await ctx.send("**ليس لديك الصلاحية!** فقط أعضاء إدارة المتجر يمكنهم استخدام هذا الأمر.")
        return

    # إنشاء زر لفتح الواجهة التفاعلية
    class OpenModalButton(View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(label="فتح واجهة إدخال المنتج", style=discord.ButtonStyle.primary)
        async def open_modal(self, interaction: discord.Interaction, button: Button):
            await interaction.response.send_modal(AddProductModal())

    # إرسال الرسالة مع الزر
    view = OpenModalButton()
    await ctx.send("اضغط على الزر أدناه لفتح واجهة إدخال المنتج:", view=view)

# تشغيل البوت
TOKEN = "TOKEN_YOU_BOT"
bot.run(TOKEN)

#bot.run()
