#!/usr/bin/env python3
import sys
import os
import json
import argparse
import base64
import requests
from dateutil import parser
import re
from datetime import datetime, timezone
from pathlib import Path

token = None

def printProgressBar(iteration, total, prefix = '', length = 60, fill = '█'):
    filledLength = int(length * iteration // total)
    bar = (fill * filledLength) + ('-' * (length - filledLength))
    percent = 100 * (iteration / float(total))
    fmt = f"\r{prefix} |{bar}| {percent:.1f}%"
    sys.stdout.write(fmt)
    # Print New Line on Complete
    if iteration == total:
        print()


def getfile(url):
    return requests.get(url, headers={'Authorization': f'token {token}'})


def getPluginJson(plugin, shortUrls, debug=False):
    if debug:
        print(f"Processing plugin: {plugin['name']}")
    if "site" in plugin:
        pluginsJson = getfile(plugin["site"]).json()
        for plugin in pluginsJson:
            if plugin["name"] == plugin["name"]:
                return plugin
        print(f'No plugin matching {plugin["name"]} found in {plugin["site"]}')
        return

    site = "https://github.com/"
    userAndProject = plugin["name"]
    userName = plugin["name"].split("/")[0]
    projectUrl = f"https://api.github.com/repos/{userAndProject}"
    releasesUrl = f"{projectUrl}/releases/tags"
    tagsUrl = f"{projectUrl}/tags"

    releaseData = None
    if 'view_only' in plugin and plugin['view_only']:
        view_only = True
    else:
        view_only = False

    if 'auto_update' in plugin and plugin['auto_update']:
        latestRelease = f"{projectUrl}/releases/latest"

        try:
            releaseData = getfile(latestRelease).json()

            match releaseData.get('message'):
                case 'Not Found':
                    print(f"\n\nERROR: {plugin['name']}, Couldn't get release information. Likely the user created a tag but no associated release.\n")
                    return None
                case 'Bad credentials':
                    print(f"\n\nERROR: Bad credentials, check access token.\n")
                    return None

            plugin['tag'] = releaseData['tag_name']

        except requests.exceptions.HTTPError:
            print(f" Unable to get url {latestRelease}")
            return None
    elif view_only:
        # No release for a view-only plugin
        pass
    else:
        releases = f"{releasesUrl}/{plugin['tag']}"
        try:
            releaseData = getfile(releases).json()
            if "message" in releaseData and releaseData["message"] == "Not Found":
                print(f"\n\nERROR: {plugin['name']}, Couldn't get release information. Likely the user created a tag but no associated release.\n")
                print(f"Tried to use URL: {releases}")
                return None
        except requests.exceptions.HTTPError:
            print(f" Unable to get url {releases}")
            return None

    commit = None
    zipUrl = None
    shortUrl = ""
    # Lookup the tag url and find the associated commit
    if not view_only:
        try:
            tagData = getfile(tagsUrl).json()
            for tag in tagData:
                if tag["name"] == plugin["tag"]:
                    commit = tag["commit"]["sha"]
                    zipUrl = tag["zipball_url"]
                    break
            if commit is None:
                print(f"Unable to associate tag {plugin['tag']} with a commit for plugin {plugin['name']}")
                return None
        except requests.exceptions.HTTPError:
            print(f" Unable to get url {tagsUrl}")
            return None

        if zipUrl in shortUrls: #avoid duplicates
            shortUrl = shortUrls[zipUrl]
        elif os.getenv("URL_SHORTENER"):
            url = os.getenv("URL_SHORTENER")
            assert url != "", "No URL_SHORTENER environment variable."
            jsonData = {"cdn_prefix": "v35.us", "url_long": zipUrl}
            r = requests.post(url, json=jsonData)
            jsonResponse = json.loads(r.text)
            if jsonResponse['error'] == '':
                shortUrl = jsonResponse["url_short"]
            assert shortUrl.find("http") == 0

    projectData = None
    try:
        projectData = getfile(projectUrl).json()
    except requests.exceptions.HTTPError:
        print(f" Unable to get url {projectUrl}")
        return None

    data = None
    if "subdir" in plugin:
        if view_only:
            pluginjson = f"{projectUrl}/contents/{plugin['subdir']}/plugin.json"
        else:
            pluginjson = f"{projectUrl}/contents/{plugin['subdir']}/plugin.json?ref={plugin['tag']}"
    else:
        if view_only:
            pluginjson = f"{projectUrl}/contents/plugin.json"
        else:
            pluginjson = f"{projectUrl}/contents/plugin.json?ref={plugin['tag']}"
    try:
        if debug:
            print(f"Getting plugin.json from {pluginjson}")
        content = getfile(pluginjson).json()['content']
        try:
            data = json.loads(base64.b64decode(content))
        except:
            print(f"\n\nInvalid json when parsing {pluginjson}\n")
            raise
        if ('longdescription' in data and len(data['longdescription']) < 100) or ('longdescription' not in data):
            try:
                readmes = ["README.md", "README.MD", "readme.md", "README", "readme", "Readme.md"]
                if "subdir" in plugin:
                    # Yes, this is suboptimal but I'd rather waste time at generation of this list to make sure we get better long descriptions
                    readmes = [f"{plugin['subdir']}/{x}" for x in readmes] + readmes
                for readmefile in readmes:
                    if view_only:
                        readmeUrl = f"{projectUrl}/contents/{readmefile}"
                    else:
                        readmeUrl = f"{projectUrl}/contents/{readmefile}?ref={plugin['tag']}"
                    readmeJson = getfile(readmeUrl).json()
                    if all (k in readmeJson for k in ("encoding", "content")):
                        if readmeJson["encoding"] == "base64":
                            data['longdescription'] = base64.b64decode(readmeJson["content"]).decode('utf-8')
                            break
            except:
                pass
        if "plugin" in data:
            # Using old style json
            data = data["plugin"]
    except requests.exceptions.HTTPError:
        print(f" Unable to get url {pluginjson}")
        return None

    requirements_txt = ""
    if not view_only:
        try:
            if "subdir" in plugin:
                req_json = getfile(f"{projectUrl}/contents/{plugin['subdir']}/requirements.txt?ref={plugin['tag']}").json()
                if not "content" in req_json: # Try top-level requirements as well
                    req_json = getfile(f"{projectUrl}/contents/requirements.txt?ref={plugin['tag']}").json()
            else:
                req_json = getfile(f"{projectUrl}/contents/requirements.txt?ref={plugin['tag']}").json()
            if "content" in req_json:
                requirements_txt = base64.b64decode(req_json["content"]).decode('utf-8')
                if requirements_txt.startswith("\ufeff"):  # Remove BOM from file contents
                    requirements_txt = requirements_txt[1:]
                requirements_txt = requirements_txt.replace("\r\n", "\n")
        except requests.exceptions.HTTPError:
            pass

    # Additional fields required for internal use
    if view_only:
        lastUpdated = int(parser.parse(projectData["updated_at"]).timestamp())
    else:
        lastUpdated = int(parser.parse(releaseData["published_at"]).timestamp())
    data["lastUpdated"] = lastUpdated
    data["projectUrl"] = site + userAndProject
    data["projectData"] = projectData
    data["projectData"]["updated_at"] = datetime.fromtimestamp(lastUpdated, timezone.utc).isoformat()
    data["authorUrl"] = site + userName
    if view_only:
        # Hack until new system is finished
        data["packageUrl"] = "https://127.0.0.1/"
        data["packageShortUrl"] = "https://127.0.0.1/"
        data["view_only"] = True
    else:
        data["packageUrl"] = zipUrl
        data["packageShortUrl"] = shortUrl
        data["view_only"] = False
    data["dependencies"] = requirements_txt

    # Replace the fwd slash with _ and then strip all non (alpha, numeric, _ )

    data["path"] = re.sub("[^a-zA-Z0-9_]", "", re.sub("/", "_", projectData["full_name"]))
    data["commit"] = commit

    # TODO: Consider adding license info directly from the repository's json data (would need to test unlicensed plugins)
    # data["license"] = {"name" : data["license"]["name"], "text": getfile(data["license"]["url"])}

    if "api" in data.keys() and isinstance(data["api"], str):
        data["api"] = [data["api"]]

    if "minimumbinaryninjaversion" in data:
        if not isinstance(data["minimumbinaryninjaversion"], int):
            data["minimumBinaryNinjaVersion"] = 0
        else:
            data["minimumBinaryNinjaVersion"] = data["minimumbinaryninjaversion"]
        del data["minimumbinaryninjaversion"]
    elif "minimumBinaryNinjaVersion" in data:
        if not isinstance(data["minimumBinaryNinjaVersion"], int):
            data["minimumBinaryNinjaVersion"] = 0
    else:
        data["minimumBinaryNinjaVersion"] = 0

    if "pluginmetadataversion" not in data:
        data["pluginmetadataversion"] = 2  # For any plugin to use v3+ schema features, they need to set this

    if ("maximumBinaryNinjaVersion" not in data or not isinstance(data["maximumBinaryNinjaVersion"], int)):
        data["maximumBinaryNinjaVersion"] = 999999
    if "platforms" not in data:
        data["platforms"] = []
    if "installinstructions" not in data:
        data["installinstructions"] = {}
    if "subdir" in plugin:
        data["subdir"] = plugin["subdir"]
    # Native plugins require this version to not produce error logs.
    if view_only and data["minimumBinaryNinjaVersion"] < 6135:
        data["minimumBinaryNinjaVersion"] = 6135
    if debug:
        print(f"Finished processing plugin: {plugin['name']}")
    return data


def main():
    parser = argparse.ArgumentParser(description="Produce 'plugins.json' for plugin repository.")
    parser.add_argument("-i", "--initialize", action="store_true", default=False,
        help="For first time running the command against the old format")
    parser.add_argument("-r", "--readmeskip", action="store_true", default=False,
        help="Skip generating a README.md")
    parser.add_argument("-l", "--listing", action="store", default="listing.json")
    parser.add_argument("-d", "--debug", action="store_true", default=False,
        help="Debugging output")
    parser.add_argument("token")
    args = parser.parse_args(sys.argv[1:])
    global token
    token = args.token

    pluginjson = Path("./plugins.json")

    oldPlugins = {}
    shortUrls = {}
    if pluginjson.exists():
        with open(pluginjson) as pluginsFile:
            for i, plugin in enumerate(json.load(pluginsFile)):
                # Create lookup for existing urls to avoid duplication
                if "packageShortUrl" in plugin and len(plugin["packageShortUrl"]) > 0:
                    shortUrls[plugin["packageUrl"]] = plugin["packageShortUrl"]
                oldPlugins[plugin["projectData"]["full_name"]] = plugin["lastUpdated"]

    allPlugins = {}
    listing = json.load(open(args.listing, "r", encoding="utf-8"))
    for i, plugin in enumerate(listing):
        printProgressBar(i, len(listing), prefix="Collecting Plugin JSON files:")
        jsonData = getPluginJson(plugin, shortUrls, debug=args.debug)
        if jsonData is not None:
            allPlugins[plugin["name"]] = jsonData
    printProgressBar(len(listing), len(listing), prefix="Collecting Plugin JSON files:")

    newPlugins = []
    updatedPlugins = []
    removedPlugins = []
    newList = []
    for i, (name, pluginData) in enumerate(allPlugins.items()):
        # printProgressBar(i, len(allPlugins), prefix="Updating plugins.json:")
        newList.append(name)
        pluginIsNew = False
        pluginIsUpdated = False
        if name not in oldPlugins:
            pluginIsNew = True
        else:
            if name not in oldPlugins:
                pluginIsUpdated = True
            else:
                pluginIsUpdated = pluginData["lastUpdated"] > oldPlugins[name]

        if pluginIsUpdated or pluginIsNew:
            if pluginIsNew:
                newPlugins.append(name)
            elif pluginIsUpdated:
                updatedPlugins.append(name)
    for name in oldPlugins:
        if name not in newList:
            removedPlugins.append(name)

    printProgressBar(len(allPlugins), len(allPlugins), prefix="Updating plugins.json:       ")
    allPluginsList = []
    for name, plugin in allPlugins.items():
        allPluginsList.append(plugin)

    print(f"{len(newPlugins)} New Plugins:")
    for plugin in newPlugins:
        print(f"\t- {plugin}")
    print(f"{len(updatedPlugins)} Updated Plugins:")
    for plugin in updatedPlugins:
        print(f"\t- {plugin}")
    print(f"{len(removedPlugins)} Removed Plugins:")
    for plugin in removedPlugins:
        print(f"\t- {plugin}")
    print(f"Writing {pluginjson}")
    with open(pluginjson, "w") as pluginsFile:
        json.dump(allPluginsList, pluginsFile, indent="    ")

    if not args.readmeskip:
        info = ""
        if Path("INFO").exists():
            info = open("INFO", encoding="utf-8").read() + u"\n"
        with open("README.md", "w", encoding="utf-8") as readme:
            readme.write(u"# Binary Ninja Plugins\n\n")
            readme.write(u"| PluginName | Author | Description | Last Updated | Type | API | License |\n")
            readme.write(u"|------------|--------|-------------|--------------|------|-----|---------|\n")

            for plugin in dict(sorted(allPlugins.items(), key=lambda x: x[1]['name'].casefold())).values():
                api = plugin["api"][0] if "api" in plugin.keys() and isinstance(plugin["api"], list) and len(plugin["api"]) > 0 else "None"
                if "type" not in plugin:
                    plugin['type'] = ["None"]
                readme.write(f"|[{plugin['name']}]({plugin['projectUrl']})"
                    f"|[{plugin['author']}]({plugin['authorUrl']})"
                    f"|{plugin['description']}"
                    f"|{datetime.fromtimestamp(plugin['lastUpdated']).date()}"
                    f"|{', '.join(sorted(plugin['type']))}"
                    f"|{api}"  # API type
                    f"|{plugin['license']['name']}|\n")
            readme.write(info)


if __name__ == "__main__":
    main()
