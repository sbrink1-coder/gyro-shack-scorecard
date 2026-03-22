# Gyro Shack Business Scorecard Dashboard

This project contains a Streamlit dashboard that displays a live business scorecard for Gyro Shack. It compares actual Net Sales against targets for multiple locations, pulling data from both the Square API and QU POS.

## ✨ Features

- **Live Data Integration**: Fetches real-time Net Sales data from Square (for the Food Truck) and QU POS (for all other retail and catering locations).
- **Target Comparison**: Compares actuals against daily targets defined in a Google Sheet.
- **KPI Monitoring**: Tracks key performance indicators:
    - **Net Sales vs. Goal**: [Actual / Target]
    - **Labor %**: [Labor Cost / Net Sales]
    - **Average Check**: [Net Sales / Transactions]
    - **Speed of Service (SOS)**
- **Color-Coded Logic**: Visual cues (Green, Yellow, Red) to quickly assess performance against targets.
- **Automated Daily Scrape**: A GitHub Actions workflow runs daily at 4:00 AM MST to fetch the previous day's data, ensuring the dashboard is always up-to-date.
- **High-Visibility UI**: The Streamlit interface is designed for clarity and high visibility on large external monitors.
- **Secure**: All API keys and passwords are handled securely using environment variables and GitHub Secrets, not hard-coded in the source.

## 🚀 Deployment

This application is designed for deployment on Streamlit Cloud.

### Prerequisites

1.  A GitHub repository containing all the code from this project.
2.  A Streamlit Cloud account.
3.  API credentials for Square and QU POS.

### Setup Steps

1.  **Push to GitHub**: Push the entire `gyro-scorecard` directory to a new GitHub repository.

2.  **Configure GitHub Secrets**: In your GitHub repository, go to `Settings > Secrets and variables > Actions` and add the following secrets:
    - `SQUARE_ACCESS_TOKEN`: Your Square API access token.
    - `QU_USERNAME`: Your QU POS username (e.g., `seth.brink`).
    - `QU_PASSWORD`: Your QU POS password.

3.  **Deploy to Streamlit Cloud**:
    - Log in to your Streamlit Cloud account.
    - Click "New app" and connect your GitHub account.
    - Select the repository you just created.
    - Ensure the "Main file path" is set to `app.py`.
    - Click "Deploy!".

4.  **Run the Initial Scrape (Optional)**:
    - To populate the dashboard with data immediately, you can manually trigger the GitHub Action.
    - Go to the `Actions` tab in your GitHub repository.
    - Select the "Daily Scorecard Scrape" workflow.
    - Click "Run workflow" on the `main` branch.

## 📁 Project Structure

```
/gyro-scorecard
├── .github/
│   └── workflows/
│       └── daily-scrape.yml  # GitHub Action for daily data scraping
├── .streamlit/
│   └── config.toml         # Streamlit theme and configuration
├── data/
│   └── scorecard_data.json # Cached data file for the dashboard
├── fetchers/
│   ├── __init__.py
│   ├── qu_fetcher.py         # Scraper for QU POS data
│   └── square_fetcher.py     # Fetcher for Square API data
├── app.py                    # The main Streamlit dashboard application
├── collect_data.py           # Main data collection script run by the GitHub Action
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```
