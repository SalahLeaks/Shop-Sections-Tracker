import requests
import json
import datetime
import pytz
import asyncio
import logging

# Configure logging
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Constants
API_URL = "https://fortnitecontent-website-prod07.ol.epicgames.com/content/api/pages/fortnite-game/mp-item-shop"
WEBHOOK_URL = "YOUR_WEBHOOK_URL"
CHECK_INTERVAL = 60  # seconds

# Load old shop data from a file
def read_old_data():
    try:
        with open("old_shop_data.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logging.warning("No previous shop data found or JSON is corrupt. Creating a new file.")
        return {}

# Save new shop data to a file
def save_data(data):
    try:
        with open("old_shop_data.json", "w") as f:
            json.dump(data, f, indent=4)
        logging.info("Updated shop data saved successfully.")
    except Exception as e:
        logging.error(f"Failed to save shop data: {e}")

# Convert a datetime object to Discord's relative timestamp format
def to_discord_timestamp(dt):
    unix_ts = int(dt.timestamp())
    return f"<t:{unix_ts}:R>"

# Send data to Discord webhook
async def send_to_discord(embed_dict):
    headers = {"Content-Type": "application/json"}
    payload = {"embeds": [embed_dict]}

    try:
        response = requests.post(WEBHOOK_URL, json=payload, headers=headers)
        if response.status_code == 204:
            logging.info("Message sent successfully to Discord webhook.")
        else:
            logging.error(f"Failed to send message: {response.status_code} - {response.text}")
    except requests.RequestException as e:
        logging.error(f"Error sending data to Discord: {e}")

    await asyncio.sleep(1)  # Avoid hitting rate limits

# Create an embed for a given section of the shop
def create_embed_for_section(section, new_section):
    metadata = section.get("metadata", {})
    background_url = metadata.get("background", {}).get("customTexture")

    display_name = section.get("displayName", "N/A")
    section_id = section.get("sectionID", "N/A")
    category = section.get("category")

    background_field = f"[Background]({background_url})" if background_url else "No Background"
    contexts = "\n".join(new_section["contexts"]) if new_section["contexts"] else "No Context"
    release_dates = "\n".join(
        [to_discord_timestamp(datetime.datetime.fromisoformat(date)) for date in new_section["release_dates"] if date]
    ) if new_section["release_dates"] else "No Release Dates"

    fields = [
        {"name": "**Display Name**", "value": display_name, "inline": True},
        {"name": "**Section ID**", "value": section_id, "inline": True},
    ]

    if category:
        fields.append({"name": "**Category**", "value": category, "inline": True})
    else:
        fields.append({"name": "**Background**", "value": background_field, "inline": True})

    second_row_fields = []
    if category:
        second_row_fields.append({"name": "**Background**", "value": background_field, "inline": True})

    second_row_fields.append({"name": "**Group Count**", "value": str(new_section["group_count"]), "inline": True})

    # Move the "billboard" field after "group_count"
    if new_section["billboard"] > 0:
        second_row_fields.append({"name": "**Billboard**", "value": str(new_section["billboard"]), "inline": True})

    fields.extend(second_row_fields)

    fields.append({"name": "**Context(s)**", "value": contexts, "inline": False})
    fields.append({"name": "**Possible Release Dates**", "value": release_dates, "inline": False})

    return {"fields": fields}

# Normalize and sort data for better comparison
def normalize_data(data):
    for section_id, section in data.items():
        if "contexts" in section:
            section["contexts"] = sorted(set(section["contexts"]))
        if "release_dates" in section:
            section["release_dates"] = sorted(section["release_dates"])
    return data

# Count billboards for each section
def count_billboards(data):
    sections = data.get("sections", [])
    billboard_counts = {}

    for section in sections:
        section_id = section.get("sectionID")
        offer_groups = section.get("metadata", {}).get("offerGroups", [])
        billboard_count = sum(1 for group in offer_groups if group.get("displayType") == "billboard")
        billboard_counts[section_id] = billboard_count

    return billboard_counts

# Process the shop data and build the message layout
async def process_shop_data():
    logging.info("Fetching Fortnite shop data...")

    try:
        response = await asyncio.to_thread(requests.get, API_URL)
        if response.status_code != 200:
            logging.error(f"Failed to fetch data: {response.status_code} - {response.text}")
            return

        data = response.json()
        sections = data.get("shopData", {}).get("sections", [])
        old_data = read_old_data()
        new_data = {}

        logging.info(f"Processing {len(sections)} shop sections...")

        tasks = []
        for section in sections:
            section_id = section.get("sectionID", "N/A")
            display_name = section.get("displayName", "N/A")
            category = section.get("category")
            metadata = section.get("metadata", {})
            background_url = metadata.get("background", {}).get("customTexture")

            new_section = {
                "display_name": display_name,
                "category": category if category else None,
                "background_url": background_url if background_url else "No Background",
                "group_count": len(metadata.get("offerGroups", [])),
                "billboard": sum(1 for group in metadata.get("offerGroups", []) if group.get("displayType") == "billboard"),
                "contexts": sorted(set(rank.get("context", "Unknown") for rank in metadata.get("stackRanks", []))),
                "release_dates": sorted(rank.get("startDate") for rank in metadata.get("stackRanks", []) if rank.get("startDate"))
            }

            new_data[section_id] = new_section

            # Compare other fields except release dates
            old_section = old_data.get(section_id, {})
            old_section_without_dates = {k: v for k, v in old_section.items() if k != "release_dates"}
            new_section_without_dates = {k: v for k, v in new_section.items() if k != "release_dates"}

            if old_section_without_dates != new_section_without_dates:
                logging.info(f"New or updated section detected: {display_name} (ID: {section_id})")
                embed_dict = create_embed_for_section(section, new_section)
                tasks.append(send_to_discord(embed_dict))

        if tasks:
            await asyncio.gather(*tasks)

        if old_data != new_data:
            logging.info("New shop data detected, updating old data file...")
            save_data(new_data)
        else:
            logging.info("No changes detected in shop data.")

    except requests.RequestException as e:
        logging.error(f"Error fetching Fortnite shop data: {e}")
    except json.JSONDecodeError:
        logging.error("Failed to decode JSON response.")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")

# Main loop
async def main_loop():
    logging.info("Logged in as Fortnite shop checker bot.")
    while True:
        await process_shop_data()
        logging.info(f"Sleeping for {CHECK_INTERVAL} seconds before next check...")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    logging.info("Starting Fortnite shop checker...")
    asyncio.run(main_loop())
