import discord
from discord.ext import commands
from discord import app_commands
import pandas as pd
import os
import json
from datetime import datetime
import time
import re
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

load_dotenv()

# =========================
# CONFIG
# =========================
GUILD_ID = 1489492813942099968
REPORT_CHANNEL_NAME = "item-reports"
LOG_CHANNEL_NAME = "bot-logs"

TOKEN = os.getenv("TOKEN")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
GOOGLE_SHEETS_TAB = os.getenv("GOOGLE_SHEETS_TAB", "Sheet1")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_SHEETS_RANGE = f"{GOOGLE_SHEETS_TAB}!A:G"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Default editor role = editor
EDITOR_ROLE_NAMES = [
    role.strip() for role in os.getenv("EDITOR_ROLE_NAMES", "editor").split(",")
    if role.strip()
]

if not TOKEN:
    raise ValueError("TOKEN not found in environment variables.")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# =========================
# TEXT NORMALIZER
# =========================
def normalize_text(text):
    text = str(text).lower().strip()
    return re.sub(r"[^a-z0-9]", "", text)


# =========================
# GOOGLE SHEETS
# =========================
def get_sheets_service():
    if not GOOGLE_SHEETS_ID:
        raise ValueError("GOOGLE_SHEETS_ID not found in environment variables.")

    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON not found in environment variables.")

    creds_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)

    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=GOOGLE_SCOPES
    )

    return build("sheets", "v4", credentials=creds)


# =========================
# LOAD DATA
# =========================
def load_data():
    try:
        service = get_sheets_service()

        result = service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEETS_ID,
            range=GOOGLE_SHEETS_RANGE
        ).execute()

        values = result.get("values", [])

        if not values:
            print("❌ Google Sheet is empty.")
            return pd.DataFrame(
                columns=["No", "name", "country", "tier", "type", "how_to_obtain", "full_release"]
            )

        headers = [str(h).strip() for h in values[0]]
        rows = values[1:]

        max_len = len(headers)
        normalized_rows = [
            row + [""] * (max_len - len(row))
            for row in rows
        ]

        df = pd.DataFrame(normalized_rows, columns=headers)
        df.columns = df.columns.str.strip()
        df = df.fillna("-").replace("", "-")

        text_columns = ["name", "type", "country", "how_to_obtain"]
        for col in text_columns:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()

        print("=== GOOGLE SHEETS DATA LOADED ===")
        print("Range:", GOOGLE_SHEETS_RANGE)
        print("Columns:", df.columns.tolist())
        print("Rows:", len(df))

        return df

    except Exception as e:
        print(f"❌ Failed to load Google Sheets data: {e}")
        return pd.DataFrame(
            columns=["No", "name", "country", "tier", "type", "how_to_obtain", "full_release"]
        )


df = load_data()


# =========================
# HELPERS
# =========================
def get_name_list():
    if "name" not in df.columns:
        return []
    return sorted(
        df["name"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda x: x != "-"]
        .unique()
        .tolist()
    )


def get_type_list():
    if "type" not in df.columns:
        return []
    return sorted(
        df["type"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda x: x != "-"]
        .unique()
        .tolist()
    )


def get_country_list():
    if "country" not in df.columns:
        return []
    return sorted(
        df["country"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda x: x != "-"]
        .unique()
        .tolist()
    )


def get_source_list():
    if "how_to_obtain" not in df.columns:
        return []
    return sorted(
        df["how_to_obtain"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda x: x != "-"]
        .unique()
        .tolist()
    )


def get_selected_item_values_before(interaction: discord.Interaction, current_index: int):
    selected_values = set()

    for index in range(1, current_index):
        field_name = f"item{index}"
        selected_value = getattr(interaction.namespace, field_name, None)

        if selected_value:
            selected_values.add(normalize_text(selected_value))

    return selected_values


def format_tier(tier_value):
    if pd.isna(tier_value):
        return "-"
    try:
        if isinstance(tier_value, (int, float)):
            return f"{tier_value:.0f}"
    except Exception:
        pass
    return str(tier_value)


def clean_country(value):
    value = str(value).strip()
    if not value or value.lower() in ["nan", "-"]:
        return "-"

    special_countries = {
        "usa": "USA",
        "u.s.a": "USA",
        "u.s.a.": "USA",
        "us": "USA",
        "u.s": "USA",
        "u.s.": "USA",
        "uk": "United Kingdom",
        "u.k": "United Kingdom",
        "u.k.": "United Kingdom",
        "ussr": "USSR",
        "uae": "UAE",
    }

    key = value.lower()
    if key in special_countries:
        return special_countries[key]

    return value.title()


def is_yes(value):
    return normalize_text(value) in ["yes", "y", "true", "1"]


def get_row_value_by_position(row, position_index, default="-"):
    try:
        value = row.iloc[position_index]
        value = str(value).strip()
        if not value or value.lower() in ["nan", "-"]:
            return default
        return value
    except Exception:
        return default


def get_full_release_value(row):
    # Prefer common header names if column G has a header.
    possible_headers = [
        "full_release",
        "full release",
        "full_release_source",
        "full release source",
        "full_release_obtain",
        "full release obtain",
    ]

    normalized_index_map = {
        normalize_text(column_name): column_name
        for column_name in row.index
    }

    for header in possible_headers:
        normalized_header = normalize_text(header)
        if normalized_header in normalized_index_map:
            column_name = normalized_index_map[normalized_header]
            value = str(row.get(column_name, "-")).strip()
            if value and value.lower() not in ["nan", "-"]:
                return value

    # Fallback: use column G by position.
    # A=0, B=1, C=2, D=3, E=4, F=5, G=6
    return get_row_value_by_position(row, 6, "-")


def get_source_display(row, full_release="no"):
    base_source = str(row.get("how_to_obtain", "-")).strip()

    if not base_source or base_source.lower() in ["nan", "-"]:
        base_source = "-"

    if not is_yes(full_release):
        return base_source

    full_release_source = get_full_release_value(row)

    if not full_release_source or full_release_source == "-":
        return base_source

    if base_source == "-":
        return full_release_source

    return f"{base_source}\n{full_release_source}"


def get_source_label(full_release="no"):
    if is_yes(full_release):
        return "📥 How to Obtain"
    return "📥 First Release"


def build_item_embed(item, description="✨ Item Overview", color=discord.Color.gold(), full_release="no"):
    embed = discord.Embed(
        title=f"📦 {item.get('name', '-')}",
        description=description,
        color=color,
    )
    embed.add_field(name="🧩 Type", value=f"*{item.get('type', '-')}*", inline=True)
    embed.add_field(name="🏆 Tier", value=f"*{format_tier(item.get('tier', '-'))}*", inline=True)
    embed.add_field(name="🌍 Country", value=clean_country(item.get("country", "-")), inline=True)
    embed.add_field(name=get_source_label(full_release), value=get_source_display(item, full_release), inline=False)
    embed.set_footer(text="Can't find item? Click Report Item below")
    return embed


def find_best_match_by_name(dataframe, name):
    search_name = normalize_text(name)

    if not search_name or "name" not in dataframe.columns:
        return pd.DataFrame()

    normalized_names = dataframe["name"].fillna("").astype(str).apply(normalize_text)

    exact_result = dataframe[normalized_names == search_name]
    if not exact_result.empty:
        return exact_result

    contains_result = dataframe[normalized_names.str.contains(search_name, na=False)]
    return contains_result


def find_best_match_by_type_and_name(dataframe, item_type, name):
    normalized_type = normalize_text(item_type)
    normalized_name = normalize_text(name)

    if (
        not normalized_type
        or not normalized_name
        or "type" not in dataframe.columns
        or "name" not in dataframe.columns
    ):
        return pd.DataFrame()

    normalized_types = dataframe["type"].fillna("").astype(str).apply(normalize_text)
    type_filtered_df = dataframe[normalized_types == normalized_type]
    type_filtered_names = type_filtered_df["name"].fillna("").astype(str).apply(normalize_text)

    exact_result = type_filtered_df[type_filtered_names == normalized_name]
    if not exact_result.empty:
        return exact_result

    contains_result = type_filtered_df[type_filtered_names.str.contains(normalized_name, na=False)]
    return contains_result


def item_exists_in_database(dataframe, item_name):
    normalized_input = normalize_text(item_name)

    if not normalized_input or "name" not in dataframe.columns:
        return False, None

    normalized_names = dataframe["name"].fillna("").astype(str).apply(normalize_text)

    exact_result = dataframe[normalized_names == normalized_input]
    if not exact_result.empty:
        return True, exact_result.iloc[0]

    if len(normalized_input) >= 3:
        partial_result = dataframe[
            normalized_names.apply(lambda existing_name: normalized_input in existing_name)
        ]
        if not partial_result.empty:
            return True, partial_result.iloc[0]

    return False, None


def get_exact_item_row_index(dataframe, item_name):
    if "name" not in dataframe.columns:
        return None, None

    normalized_input = normalize_text(item_name)
    if not normalized_input:
        return None, None

    normalized_names = dataframe["name"].fillna("").astype(str).apply(normalize_text)
    matched_indices = dataframe.index[normalized_names == normalized_input].tolist()

    if not matched_indices:
        return None, None

    idx = matched_indices[0]
    return idx, dataframe.iloc[idx]


def get_next_no_value(dataframe):
    if "No" not in dataframe.columns:
        return str(len(dataframe) + 1)

    numeric_values = pd.to_numeric(dataframe["No"], errors="coerce").dropna()
    if numeric_values.empty:
        return "1"

    return str(int(numeric_values.max()) + 1)


def user_has_editor_access(member: discord.Member):
    return any(role.name in EDITOR_ROLE_NAMES for role in member.roles)


def make_editor_denied_message():
    roles_text = ", ".join(f"`{role}`" for role in EDITOR_ROLE_NAMES)
    return f"⛔ You need one of these roles to use this command: {roles_text}"


def append_item_to_sheet(no_value, name, country, tier, item_type, how_to_obtain):
    service = get_sheets_service()

    body = {
        "values": [[
            str(no_value),
            str(name).strip(),
            str(country).strip(),
            str(tier).strip(),
            str(item_type).strip(),
            str(how_to_obtain).strip(),
            "",
        ]]
    }

    service.spreadsheets().values().append(
        spreadsheetId=GOOGLE_SHEETS_ID,
        range=f"{GOOGLE_SHEETS_TAB}!A:G",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body
    ).execute()


def update_item_in_sheet(sheet_row_number, no_value, name, country, tier, item_type, how_to_obtain):
    service = get_sheets_service()

    body = {
        "values": [[
            str(no_value),
            str(name).strip(),
            str(country).strip(),
            str(tier).strip(),
            str(item_type).strip(),
            str(how_to_obtain).strip(),
            "",
        ]]
    }

    service.spreadsheets().values().update(
        spreadsheetId=GOOGLE_SHEETS_ID,
        range=f"{GOOGLE_SHEETS_TAB}!A{sheet_row_number}:G{sheet_row_number}",
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()


def delete_item_from_sheet(sheet_row_number):
    service = get_sheets_service()

    spreadsheet = service.spreadsheets().get(
        spreadsheetId=GOOGLE_SHEETS_ID
    ).execute()

    sheet_id = None
    for sheet in spreadsheet.get("sheets", []):
        properties = sheet.get("properties", {})
        if properties.get("title") == GOOGLE_SHEETS_TAB:
            sheet_id = properties.get("sheetId")
            break

    if sheet_id is None:
        raise ValueError(f"Sheet tab '{GOOGLE_SHEETS_TAB}' not found.")

    service.spreadsheets().batchUpdate(
        spreadsheetId=GOOGLE_SHEETS_ID,
        body={
            "requests": [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": sheet_row_number - 1,
                            "endIndex": sheet_row_number,
                        }
                    }
                }
            ]
        }
    ).execute()


# =========================
# CHANNEL HELPERS
# =========================
async def get_report_channel(interaction: discord.Interaction):
    if interaction.guild is None:
        return None
    return discord.utils.get(interaction.guild.text_channels, name=REPORT_CHANNEL_NAME)


async def get_log_channel(interaction: discord.Interaction):
    if interaction.guild is None:
        return None
    return discord.utils.get(interaction.guild.text_channels, name=LOG_CHANNEL_NAME)


async def send_log_embed(interaction: discord.Interaction, embed: discord.Embed):
    log_channel = await get_log_channel(interaction)
    if log_channel is None:
        return
    try:
        await log_channel.send(embed=embed)
    except Exception as e:
        print(f"❌ Failed to send log message: {e}")


async def is_item_already_reported(report_channel: discord.TextChannel, item_name: str):
    normalized_input = normalize_text(item_name)

    if not normalized_input:
        return False

    try:
        async for message in report_channel.history(limit=1000):
            if not message.embeds:
                continue

            embed = message.embeds[0]

            for field in embed.fields:
                if field.name == "📦 Item Name":
                    existing_item = field.value.replace("`", "").strip()
                    if normalize_text(existing_item) == normalized_input:
                        return True

                if field.name == "🔎 Normalized Key":
                    existing_key = field.value.replace("`", "").strip()
                    if existing_key == normalized_input:
                        return True

    except discord.Forbidden:
        print("❌ Missing permission: Read Message History or View Channel for report channel.")
        raise
    except Exception as e:
        print(f"❌ Failed to check report history: {e}")
        raise

    return False


async def check_report_channel_permissions(interaction: discord.Interaction):
    report_channel = await get_report_channel(interaction)

    if report_channel is None:
        return None, "missing_channel"

    permissions = report_channel.permissions_for(interaction.guild.me)

    missing_permissions = []

    if not permissions.view_channel:
        missing_permissions.append("View Channel")
    if not permissions.read_message_history:
        missing_permissions.append("Read Message History")
    if not permissions.send_messages:
        missing_permissions.append("Send Messages")
    if not permissions.embed_links:
        missing_permissions.append("Embed Links")

    if missing_permissions:
        return report_channel, missing_permissions

    return report_channel, []


# =========================
# AUTOCOMPLETE
# =========================
async def name_autocomplete(interaction: discord.Interaction, current: str):
    name_list = get_name_list()
    current_normalized = normalize_text(current)

    if not current.strip():
        return [app_commands.Choice(name=name, value=name) for name in name_list[:25]]

    return [
        app_commands.Choice(name=name, value=name)
        for name in name_list
        if current_normalized in normalize_text(name)
    ][:25]


async def item_autocomplete_for_index(
    interaction: discord.Interaction,
    current: str,
    current_index: int,
):
    name_list = get_name_list()
    current_normalized = normalize_text(current)
    selected_values = get_selected_item_values_before(interaction, current_index)

    filtered_names = [
        name for name in name_list
        if normalize_text(name) not in selected_values
    ]

    if not current.strip():
        return [
            app_commands.Choice(name=name, value=name)
            for name in filtered_names[:25]
        ]

    return [
        app_commands.Choice(name=name, value=name)
        for name in filtered_names
        if current_normalized in normalize_text(name)
    ][:25]


async def item1_autocomplete(interaction: discord.Interaction, current: str):
    return await item_autocomplete_for_index(interaction, current, 1)


async def item2_autocomplete(interaction: discord.Interaction, current: str):
    return await item_autocomplete_for_index(interaction, current, 2)


async def item3_autocomplete(interaction: discord.Interaction, current: str):
    return await item_autocomplete_for_index(interaction, current, 3)


async def item4_autocomplete(interaction: discord.Interaction, current: str):
    return await item_autocomplete_for_index(interaction, current, 4)


async def item5_autocomplete(interaction: discord.Interaction, current: str):
    return await item_autocomplete_for_index(interaction, current, 5)


async def item6_autocomplete(interaction: discord.Interaction, current: str):
    return await item_autocomplete_for_index(interaction, current, 6)


async def item7_autocomplete(interaction: discord.Interaction, current: str):
    return await item_autocomplete_for_index(interaction, current, 7)


async def item8_autocomplete(interaction: discord.Interaction, current: str):
    return await item_autocomplete_for_index(interaction, current, 8)


async def item9_autocomplete(interaction: discord.Interaction, current: str):
    return await item_autocomplete_for_index(interaction, current, 9)


async def item10_autocomplete(interaction: discord.Interaction, current: str):
    return await item_autocomplete_for_index(interaction, current, 10)


async def type_autocomplete(interaction: discord.Interaction, current: str):
    type_list = get_type_list()
    current_normalized = normalize_text(current)

    if not current.strip():
        return [app_commands.Choice(name=t, value=t) for t in type_list[:25]]

    return [
        app_commands.Choice(name=t, value=t)
        for t in type_list
        if current_normalized in normalize_text(t)
    ][:25]


async def country_autocomplete(interaction: discord.Interaction, current: str):
    country_list = get_country_list()
    current_normalized = normalize_text(current)

    if not current.strip():
        return [app_commands.Choice(name=c, value=c) for c in country_list[:25]]

    return [
        app_commands.Choice(name=c, value=c)
        for c in country_list
        if current_normalized in normalize_text(c)
    ][:25]


async def source_autocomplete(interaction: discord.Interaction, current: str):
    source_list = get_source_list()
    current_normalized = normalize_text(current)

    if not current.strip():
        return [app_commands.Choice(name=s, value=s) for s in source_list[:25]]

    return [
        app_commands.Choice(name=s, value=s)
        for s in source_list
        if current_normalized in normalize_text(s)
    ][:25]


async def tier_autocomplete(interaction: discord.Interaction, current: str):
    tier_choices = ["1", "2", "3"]
    normalized_current = normalize_text(current)

    if not current.strip():
        return [app_commands.Choice(name=t, value=t) for t in tier_choices]

    return [
        app_commands.Choice(name=t, value=t)
        for t in tier_choices
        if normalized_current in normalize_text(t)
    ][:25]


async def full_release_autocomplete(interaction: discord.Interaction, current: str):
    choices = ["yes", "no"]
    normalized_current = normalize_text(current)

    if not current.strip():
        return [app_commands.Choice(name=choice, value=choice) for choice in choices]

    return [
        app_commands.Choice(name=choice, value=choice)
        for choice in choices
        if normalized_current in normalize_text(choice)
    ][:25]


async def name_by_type_autocomplete(interaction: discord.Interaction, current: str):
    selected_type = getattr(interaction.namespace, "type", None)

    if "name" not in df.columns or "type" not in df.columns:
        return []

    filtered_df = df.copy()

    if selected_type:
        selected_type_normalized = normalize_text(selected_type)
        filtered_df = filtered_df[
            filtered_df["type"].fillna("").astype(str).apply(normalize_text)
            == selected_type_normalized
        ]

    name_list = sorted(
        filtered_df["name"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda x: x != "-"]
        .unique()
        .tolist()
    )

    current_normalized = normalize_text(current)

    if not current.strip():
        return [app_commands.Choice(name=name, value=name) for name in name_list[:25]]

    return [
        app_commands.Choice(name=name, value=name)
        for name in name_list
        if current_normalized in normalize_text(name)
    ][:25]


# =========================
# REPORT SYSTEM
# =========================
class ReportModal(discord.ui.Modal, title="Report Missing Item"):
    item_name = discord.ui.TextInput(
        label="Item Name",
        placeholder="Enter item name...",
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        global df

        item_input = self.item_name.value.strip()

        if not item_input:
            await interaction.response.send_message(
                "⚠️ Item name cannot be empty!",
                ephemeral=True,
            )
            return

        item_exists, _ = item_exists_in_database(df, item_input)
        if item_exists:
            await interaction.response.send_message(
                "⚠️ This item already exists in the database.",
                ephemeral=True,
            )
            return

        report_channel, permission_status = await check_report_channel_permissions(interaction)

        if permission_status == "missing_channel":
            await interaction.response.send_message(
                f"❌ Report channel `#{REPORT_CHANNEL_NAME}` not found.",
                ephemeral=True,
            )
            return

        if permission_status:
            missing_text = "\n".join(f"- {permission}" for permission in permission_status)
            await interaction.response.send_message(
                f"❌ Bot is missing permission in `#{REPORT_CHANNEL_NAME}`:\n{missing_text}",
                ephemeral=True,
            )
            return

        try:
            already_reported = await is_item_already_reported(report_channel, item_input)
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ Bot cannot read report history in `#{REPORT_CHANNEL_NAME}`. "
                "Please enable View Channel and Read Message History.",
                ephemeral=True,
            )
            return
        except Exception:
            await interaction.response.send_message(
                "❌ Failed to check old reports. Please try again later.",
                ephemeral=True,
            )
            return

        if already_reported:
            await interaction.response.send_message(
                "⚠️ This item has already been reported!",
                ephemeral=True,
            )
            return

        normalized_item = normalize_text(item_input)

        report_embed = discord.Embed(
            title="🚨 Missing Item Report",
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )
        report_embed.add_field(
            name="👤 Reported By",
            value=f"{interaction.user.mention}\n`{interaction.user}`",
            inline=False,
        )
        report_embed.add_field(
            name="📦 Item Name",
            value=f"`{item_input}`",
            inline=False,
        )
        report_embed.add_field(
            name="🔎 Normalized Key",
            value=f"`{normalized_item}`",
            inline=False,
        )
        report_embed.add_field(
            name="📍 Source Channel",
            value=interaction.channel.mention if interaction.channel else "-",
            inline=False,
        )
        report_embed.set_footer(text=f"User ID: {interaction.user.id}")

        try:
            await report_channel.send(embed=report_embed)
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ Bot cannot send report to `#{REPORT_CHANNEL_NAME}`. "
                "Please enable Send Messages and Embed Links.",
                ephemeral=True,
            )
            return
        except Exception as e:
            print(f"❌ Failed to send report: {e}")
            await interaction.response.send_message(
                "❌ Failed to send report. Please try again later.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ Report sent to #{REPORT_CHANNEL_NAME}!",
            ephemeral=True,
        )


class ReportView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Report Item",
        style=discord.ButtonStyle.danger,
        custom_id="report_missing_item_button",
    )
    async def report(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReportModal())


# =========================
# COMMAND: /check
# =========================
@bot.tree.command(
    name="check",
    description="Check item by name",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    name="Item name",
    full_release="yes = show First Release + Full Release",
)
@app_commands.autocomplete(name=name_autocomplete, full_release=full_release_autocomplete)
async def check(interaction: discord.Interaction, name: str, full_release: str = "no"):
    global df

    result = find_best_match_by_name(df, name)

    if result.empty:
        await interaction.response.send_message(
            "❌ Data not found!",
            ephemeral=True,
        )
        return

    item = result.iloc[0]
    embed = build_item_embed(item, full_release=full_release)

    await interaction.response.send_message(embed=embed, view=ReportView())


# =========================
# COMMAND: /type
# =========================
@bot.tree.command(
    name="type",
    description="Check item by type and name",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    type="Item type",
    name="Item name",
    full_release="yes = show First Release + Full Release",
)
@app_commands.autocomplete(type=type_autocomplete, name=name_by_type_autocomplete, full_release=full_release_autocomplete)
async def type_command(interaction: discord.Interaction, type: str, name: str, full_release: str = "no"):
    global df

    result = find_best_match_by_type_and_name(df, type, name)

    if result.empty:
        await interaction.response.send_message(
            "❌ Data not found!",
            ephemeral=True,
        )
        return

    item = result.iloc[0]
    embed = build_item_embed(
        item,
        description="✨ Item Overview by Type",
        color=discord.Color.blue(),
        full_release=full_release,
    )

    await interaction.response.send_message(embed=embed, view=ReportView())


# =========================
# COMMAND: /item
# =========================
@bot.tree.command(
    name="item",
    description="Check up to 10 items by name",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    item1="First item name",
    item2="Second item name",
    item3="Third item name",
    item4="Fourth item name",
    item5="Fifth item name",
    item6="Sixth item name",
    item7="Seventh item name",
    item8="Eighth item name",
    item9="Ninth item name",
    item10="Tenth item name",
    full_release="yes = show First Release + Full Release",
)
@app_commands.autocomplete(
    item1=item1_autocomplete,
    item2=item2_autocomplete,
    item3=item3_autocomplete,
    item4=item4_autocomplete,
    item5=item5_autocomplete,
    item6=item6_autocomplete,
    item7=item7_autocomplete,
    item8=item8_autocomplete,
    item9=item9_autocomplete,
    item10=item10_autocomplete,
    full_release=full_release_autocomplete,
)
async def item_command(
    interaction: discord.Interaction,
    item1: str,
    item2: str | None = None,
    item3: str | None = None,
    item4: str | None = None,
    item5: str | None = None,
    item6: str | None = None,
    item7: str | None = None,
    item8: str | None = None,
    item9: str | None = None,
    item10: str | None = None,
    full_release: str = "no",
):
    global df

    raw_items = [item1, item2, item3, item4, item5, item6, item7, item8, item9, item10]

    item_inputs = []
    skipped_duplicates = []
    seen_items = set()

    for raw_item in raw_items:
        if not raw_item or not raw_item.strip():
            continue

        cleaned_item = raw_item.strip()
        normalized_item = normalize_text(cleaned_item)

        if normalized_item in seen_items:
            skipped_duplicates.append(cleaned_item)
            continue

        seen_items.add(normalized_item)
        item_inputs.append(cleaned_item)

    if not item_inputs:
        await interaction.response.send_message(
            "❌ Please enter at least 1 unique item name.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="📦 Multi Item Check",
        description=f"Checking {len(item_inputs)} unique item(s)",
        color=discord.Color.purple(),
    )

    found_count = 0
    not_found_count = 0

    for item_name in item_inputs:
        result = find_best_match_by_name(df, item_name)

        if result.empty:
            not_found_count += 1
            embed.add_field(
                name=f"❌ {item_name}",
                value="Data not found",
                inline=False,
            )
            continue

        item = result.iloc[0]
        found_count += 1

        embed.add_field(
            name=f"✅ {item.get('name', item_name)}",
            value=(
                f"**Type:** {item.get('type', '-')}\n"
                f"**Tier:** {format_tier(item.get('tier', '-'))}\n"
                f"**Country:** {clean_country(item.get('country', '-'))}\n"
                f"**{get_source_label(full_release).replace('📥 ', '')}:** {get_source_display(item, full_release)}"
            ),
            inline=False,
        )

    if skipped_duplicates:
        embed.add_field(
            name="⚠️ Skipped Duplicate",
            value=", ".join(f"`{item}`" for item in skipped_duplicates),
            inline=False,
        )

    embed.set_footer(text=f"Found: {found_count} | Not Found: {not_found_count} | Skipped: {len(skipped_duplicates)}")

    if not_found_count > 0:
        await interaction.response.send_message(embed=embed, view=ReportView())
    else:
        await interaction.response.send_message(embed=embed)


# =========================
# COMMAND: /add
# =========================
@bot.tree.command(
    name="add",
    description="Add a new item to Google Sheets",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    name="Item name",
    country="Country",
    tier="Tier",
    type="Item type",
    how_to_obtain="How to obtain the item",
)
@app_commands.autocomplete(
    country=country_autocomplete,
    tier=tier_autocomplete,
    type=type_autocomplete,
    how_to_obtain=source_autocomplete,
)
async def add_command(
    interaction: discord.Interaction,
    name: str,
    country: str,
    tier: str,
    type: str,
    how_to_obtain: str,
):
    global df

    if not isinstance(interaction.user, discord.Member) or not user_has_editor_access(interaction.user):
        await interaction.response.send_message(
            make_editor_denied_message(),
            ephemeral=True,
        )
        return

    clean_name = name.strip()
    clean_country_value = country.strip()
    clean_tier = tier.strip()
    clean_type_value = type.strip()
    clean_source = how_to_obtain.strip()

    if not all([clean_name, clean_country_value, clean_tier, clean_type_value, clean_source]):
        await interaction.response.send_message(
            "❌ All fields are required.",
            ephemeral=True,
        )
        return

    exists, _ = item_exists_in_database(df, clean_name)
    if exists:
        await interaction.response.send_message(
            "⚠️ This item already exists in the database.",
            ephemeral=True,
        )
        return

    try:
        next_no = get_next_no_value(df)
        append_item_to_sheet(
            next_no,
            clean_name,
            clean_country_value,
            clean_tier,
            clean_type_value,
            clean_source,
        )
        df = load_data()

        embed = discord.Embed(
            title="✅ Item Added",
            color=discord.Color.green(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="📦 Name", value=clean_name, inline=False)
        embed.add_field(name="🌍 Country", value=clean_country_value, inline=True)
        embed.add_field(name="🏆 Tier", value=clean_tier, inline=True)
        embed.add_field(name="🧩 Type", value=clean_type_value, inline=True)
        embed.add_field(name="📥 Source", value=clean_source, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

        log_embed = discord.Embed(
            title="➕ Item Added",
            color=discord.Color.green(),
            timestamp=datetime.now(),
        )
        log_embed.add_field(
            name="👤 By",
            value=f"{interaction.user.mention}\n`{interaction.user}`",
            inline=False,
        )
        log_embed.add_field(name="📦 Name", value=clean_name, inline=False)
        log_embed.add_field(name="🌍 Country", value=clean_country_value, inline=True)
        log_embed.add_field(name="🏆 Tier", value=clean_tier, inline=True)
        log_embed.add_field(name="🧩 Type", value=clean_type_value, inline=True)
        log_embed.add_field(name="📥 Source", value=clean_source, inline=False)
        await send_log_embed(interaction, log_embed)

    except Exception as e:
        print(f"❌ Failed to add item: {e}")
        await interaction.response.send_message(
            "❌ Failed to add item to Google Sheets.",
            ephemeral=True,
        )


# =========================
# COMMAND: /edit
# =========================
@bot.tree.command(
    name="edit",
    description="Edit an existing item in Google Sheets",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    name="Existing item name",
    new_country="New country",
    new_tier="New tier",
    new_type="New type",
    new_how_to_obtain="New source",
)
@app_commands.autocomplete(
    name=name_autocomplete,
    new_country=country_autocomplete,
    new_tier=tier_autocomplete,
    new_type=type_autocomplete,
    new_how_to_obtain=source_autocomplete,
)
async def edit_command(
    interaction: discord.Interaction,
    name: str,
    new_country: str | None = None,
    new_tier: str | None = None,
    new_type: str | None = None,
    new_how_to_obtain: str | None = None,
):
    global df

    if not isinstance(interaction.user, discord.Member) or not user_has_editor_access(interaction.user):
        await interaction.response.send_message(
            make_editor_denied_message(),
            ephemeral=True,
        )
        return

    if not any([new_country, new_tier, new_type, new_how_to_obtain]):
        await interaction.response.send_message(
            "❌ Please provide at least 1 new value to edit.",
            ephemeral=True,
        )
        return

    row_index, item_row = get_exact_item_row_index(df, name)
    if row_index is None or item_row is None:
        await interaction.response.send_message(
            "❌ Exact item name not found for editing.",
            ephemeral=True,
        )
        return

    sheet_row_number = row_index + 2

    current_no = item_row.get("No", get_next_no_value(df))
    updated_name = str(item_row.get("name", name)).strip()
    old_country = str(item_row.get("country", "-")).strip()
    old_tier = str(item_row.get("tier", "-")).strip()
    old_type = str(item_row.get("type", "-")).strip()
    old_source = str(item_row.get("how_to_obtain", "-")).strip()

    updated_country = new_country.strip() if new_country else old_country
    updated_tier = new_tier.strip() if new_tier else old_tier
    updated_type = new_type.strip() if new_type else old_type
    updated_source = new_how_to_obtain.strip() if new_how_to_obtain else old_source

    try:
        update_item_in_sheet(
            sheet_row_number,
            current_no,
            updated_name,
            updated_country,
            updated_tier,
            updated_type,
            updated_source,
        )
        df = load_data()

        embed = discord.Embed(
            title="✏️ Item Updated",
            color=discord.Color.orange(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="📦 Name", value=updated_name, inline=False)
        embed.add_field(name="🌍 Country", value=updated_country, inline=True)
        embed.add_field(name="🏆 Tier", value=updated_tier, inline=True)
        embed.add_field(name="🧩 Type", value=updated_type, inline=True)
        embed.add_field(name="📥 Source", value=updated_source, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

        log_embed = discord.Embed(
            title="✏️ Item Edited",
            color=discord.Color.orange(),
            timestamp=datetime.now(),
        )
        log_embed.add_field(
            name="👤 By",
            value=f"{interaction.user.mention}\n`{interaction.user}`",
            inline=False,
        )
        log_embed.add_field(name="📦 Name", value=updated_name, inline=False)
        log_embed.add_field(name="🌍 Country", value=f"{old_country} → {updated_country}", inline=False)
        log_embed.add_field(name="🏆 Tier", value=f"{old_tier} → {updated_tier}", inline=False)
        log_embed.add_field(name="🧩 Type", value=f"{old_type} → {updated_type}", inline=False)
        log_embed.add_field(name="📥 Source", value=f"{old_source} → {updated_source}", inline=False)
        await send_log_embed(interaction, log_embed)

    except Exception as e:
        print(f"❌ Failed to edit item: {e}")
        await interaction.response.send_message(
            "❌ Failed to edit item in Google Sheets.",
            ephemeral=True,
        )


# =========================
# COMMAND: /delete
# =========================
@bot.tree.command(
    name="delete",
    description="Delete an item from Google Sheets",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(name="Exact item name to delete")
@app_commands.autocomplete(name=name_autocomplete)
async def delete_command(interaction: discord.Interaction, name: str):
    global df

    if not isinstance(interaction.user, discord.Member) or not user_has_editor_access(interaction.user):
        await interaction.response.send_message(
            make_editor_denied_message(),
            ephemeral=True,
        )
        return

    row_index, item_row = get_exact_item_row_index(df, name)
    if row_index is None or item_row is None:
        await interaction.response.send_message(
            "❌ Exact item name not found for deletion.",
            ephemeral=True,
        )
        return

    sheet_row_number = row_index + 2
    item_name = str(item_row.get("name", name)).strip()
    item_country = str(item_row.get("country", "-")).strip()
    item_tier = str(item_row.get("tier", "-")).strip()
    item_type = str(item_row.get("type", "-")).strip()
    item_source = str(item_row.get("how_to_obtain", "-")).strip()

    try:
        delete_item_from_sheet(sheet_row_number)
        df = load_data()

        await interaction.response.send_message(
            f"🗑️ Deleted item: `{item_name}`",
            ephemeral=True,
        )

        log_embed = discord.Embed(
            title="🗑️ Item Deleted",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(),
        )
        log_embed.add_field(
            name="👤 By",
            value=f"{interaction.user.mention}\n`{interaction.user}`",
            inline=False,
        )
        log_embed.add_field(name="📦 Name", value=item_name, inline=False)
        log_embed.add_field(name="🌍 Country", value=item_country, inline=True)
        log_embed.add_field(name="🏆 Tier", value=item_tier, inline=True)
        log_embed.add_field(name="🧩 Type", value=item_type, inline=True)
        log_embed.add_field(name="📥 Source", value=item_source, inline=False)
        await send_log_embed(interaction, log_embed)

    except Exception as e:
        print(f"❌ Failed to delete item: {e}")
        await interaction.response.send_message(
            "❌ Failed to delete item from Google Sheets.",
            ephemeral=True,
        )


# =========================
# COMMAND: /reload
# =========================
@bot.tree.command(
    name="reload",
    description="Reload Google Sheets data",
    guild=discord.Object(id=GUILD_ID),
)
async def reload(interaction: discord.Interaction):
    global df
    df = load_data()
    await interaction.response.send_message("✅ Data reloaded!", ephemeral=True)

    log_embed = discord.Embed(
        title="🔄 Database Reloaded",
        color=discord.Color.blurple(),
        timestamp=datetime.now(),
    )
    log_embed.add_field(
        name="👤 By",
        value=f"{interaction.user.mention}\n`{interaction.user}`",
        inline=False,
    )
    log_embed.add_field(
        name="📊 Rows Loaded",
        value=str(len(df)),
        inline=False,
    )
    await send_log_embed(interaction, log_embed)


# =========================
# COMMAND: /reportperms
# =========================
@bot.tree.command(
    name="reportperms",
    description="Check bot permission for item-reports channel",
    guild=discord.Object(id=GUILD_ID),
)
async def reportperms(interaction: discord.Interaction):
    report_channel, permission_status = await check_report_channel_permissions(interaction)

    if permission_status == "missing_channel":
        await interaction.response.send_message(
            f"❌ Report channel `#{REPORT_CHANNEL_NAME}` not found.",
            ephemeral=True,
        )
        return

    if permission_status:
        missing_text = "\n".join(f"- {permission}" for permission in permission_status)
        await interaction.response.send_message(
            f"⚠️ Missing permission in `#{REPORT_CHANNEL_NAME}`:\n{missing_text}",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"✅ Bot has all required permissions in `#{REPORT_CHANNEL_NAME}`:\n"
        "- View Channel\n"
        "- Read Message History\n"
        "- Send Messages\n"
        "- Embed Links",
        ephemeral=True,
    )


# =========================
# COMMAND: /ping
# =========================
@bot.tree.command(
    name="ping",
    description="Show bot latency and websocket ping",
    guild=discord.Object(id=GUILD_ID),
)
async def ping(interaction: discord.Interaction):
    start_time = time.perf_counter()
    websocket_ping = round(bot.latency * 1000)

    await interaction.response.send_message("🏓 Calculating ping...", ephemeral=True)

    end_time = time.perf_counter()
    total_ping = round((end_time - start_time) * 1000)

    embed = discord.Embed(
        title="🏓 Pong!",
        color=discord.Color.green(),
    )
    embed.add_field(name="📡 WebSocket Ping", value=f"`{websocket_ping} ms`", inline=False)
    embed.add_field(name="⚡ Total Response Ping", value=f"`{total_ping} ms`", inline=False)
    embed.set_footer(text="Check Item Bot")

    await interaction.edit_original_response(content=None, embed=embed)


# =========================
# READY EVENT
# =========================
@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)

    try:
        bot.add_view(ReportView())
    except Exception:
        pass

    synced = await bot.tree.sync(guild=guild)

    print(f"✅ Synced {len(synced)} guild command(s)")
    print(f"✅ Bot ready! {bot.user}")


# =========================
# RUN
# =========================
bot.run(TOKEN)
