# Convai Omniverse Extension
## Introduction
The Convai Omniverse Extension provides seamless integration between [Convai](https://convai.com/) API and Omniverse, allowing users to connect their 3D character assets with intelligent conversational agents. With this extension, users can define their character's backstory and voice at Convai and easily connect the character using its character ID.

## Installation
To install the Convai Omniverse Extension, follow these steps:
1. Clone the latest version of the repo.
2. Open Omniverse app of your choice (e.g Code) and from the `Window` menu click `Extensions`.
3. In the extensions tab, click the gear icon in the top right.
    <p align="left">
    <img height="350" src="images/extensions.png?raw=true">
    </p>
4. Click the green plus icon in the `Edit` column and add the absolute path to the `exts` folder found in the repository directory.
    <p align="left">
    <img height="350" src="images/SearchPath.png?raw=true">
    </p>
5. Select the `Third Party` tab and search for `Convai` in the top left search bar, make sure to check `Enabled` - Note: This will freeze Omniverse for a 1-2 minutes.
    <p align="left">
    <img height="250" src="images/ConvaiSearch.png?raw=true">
    </p>
6. The Convai window should appear, drag it and dock it in any suitable area of the UI.
7. If the Convai window does not appear, go to the `Window` menu and select `Convai` from the list.

## Configuration
To add your API Key and Character ID, follow these steps:
1. Sign up at [Convai](https://convai.com/).
2. On the website click the gear icon in the top-right corner of the playground then copy and paste the API key into the `Convai API Key` field in the Convai extension window.
3. Go to the [Dashboard](https://convai.com/pipeline/dashboard) and on the left panel and either create a new character or select a sample one.
4. Copy the Character ID and paste it in the `Character ID` field in the extension window.

## Actions:
Actions can be used to trigger events with the same name as the action in the `Action graph`. They can be used to run animations based on the action received. To try out actions:
1. Add a few comma seperated actions to `Comma seperated actions` field (e.g jump, kick, dance, etc.).
2. The character will select one of the actions based on the conversation and run any event with the same name as the action in the `Action Graph`.

## Running the Demo
1. Open your chosen Omniverse app (e.g., Code).
2. Go to `File->Open` and navigate to the repo directory.
3. Navigate to `<repo directory>/ConvaiDemoStage/ConvaiDemo.usd` and click `open it.
4. Click the `play` button from the `Toolbar` menu on the left.
    <p align="left">
    <img height="350" src="images/PlayToolbar.png?raw=true">
    </p>
5. Click `Start Talking` in the `Convai` window to talk to the character then click `Stop` to send the request.

## Notes
- The extension is tested in Omniverse Code, but you are welcome to try it out in other apps as well.
- The demo stage includes only talk and idle animations. However, it is possible to add more animations and trigger them using the action selected by the character. More on that in the future.