import os
import sys
import tempfile

import click

from preswald.engine.telemetry import TelemetryService


# Create a temporary directory for IPC
TEMP_DIR = os.path.join(tempfile.gettempdir(), "preswald")
os.makedirs(TEMP_DIR, exist_ok=True)

# Initialize telemetry service
telemetry = TelemetryService()


@click.group()
@click.version_option()
def cli():
    """
    Preswald CLI - A lightweight framework for interactive data apps.
    """
    pass


@cli.command()
@click.argument("name", default="preswald_project")
def init(name):
    """
    Initialize a new Preswald project.

    This creates a directory with boilerplate files like `hello.py` and `preswald.toml`.
    """
    from preswald.utils import generate_slug, read_template

    try:
        os.makedirs(name, exist_ok=True)
        os.makedirs(os.path.join(name, "images"), exist_ok=True)
        os.makedirs(os.path.join(name, "data"), exist_ok=True)

        # Generate a unique slug for the project
        project_slug = generate_slug(name)

        # Copy default branding files from package resources
        import shutil
        from importlib.resources import as_file, files

        # Using a context manager to get the actual file path
        with as_file(files("preswald").joinpath("static/favicon.ico")) as path:
            shutil.copy2(path, os.path.join(name, "images", "favicon.ico"))

        with as_file(files("preswald").joinpath("static/logo.png")) as path:
            shutil.copy2(path, os.path.join(name, "images", "logo.png"))

        file_templates = {
            "hello.py": "hello.py",
            "preswald.toml": "preswald.toml",
            "secrets.toml": "secrets.toml",
            ".gitignore": "gitignore",
            "pyproject.toml": "pyproject.toml",
            "data/sample.csv": "sample.csv",
        }

        for file_name, template_name in file_templates.items():
            content = read_template(template_name)

            # Replace the default slug in preswald.toml with the generated one
            if file_name == "preswald.toml":
                content = content.replace(
                    'slug = "preswald-project"', f'slug = "{project_slug}"'
                )

            with open(os.path.join(name, file_name), "w") as f:
                f.write(content)

        # Track initialization
        telemetry.track_command(
            "init", {"project_name": name, "project_slug": project_slug}
        )

        click.echo(f"Initialized a new Preswald project in '{name}/' 🎉!")
        click.echo(f"Project slug: {project_slug}")
    except Exception as e:
        click.echo(f"Error initializing project: {e} ❌")


@cli.command()
@click.option("--port", default=8501, help="Port to run the server on.")
@click.option(
    "--log-level",
    type=click.Choice(
        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False
    ),
    default=None,
    help="Set the logging level (overrides config file)",
)
@click.option(
    "--disable-new-tab",
    is_flag=True,
    default=False,
    help="Disable automatically opening a new browser tab",
)
def run(port, log_level, disable_new_tab):
    """
    Run a Preswald app from the current directory.

    Looks for preswald.toml in the current directory and runs the script specified in the entrypoint.
    """
    config_path = "preswald.toml"
    if not os.path.exists(config_path):
        click.echo("Error: preswald.toml not found in current directory. ❌")
        click.echo("Make sure you're in a Preswald project directory.")
        return

    import tomli

    from preswald.main import start_server
    from preswald.utils import configure_logging, read_port_from_config

    try:
        with open(config_path, "rb") as f:
            config = tomli.load(f)
    except Exception as e:
        click.echo(f"Error reading preswald.toml: {e} ❌")
        return

    if "project" not in config or "entrypoint" not in config["project"]:
        click.echo(
            "Error: entrypoint not defined in preswald.toml under [project] section. ❌"
        )
        return

    script = config["project"]["entrypoint"]
    if not os.path.exists(script):
        click.echo(f"Error: Entrypoint script '{script}' not found. ❌")
        return

    log_level = configure_logging(config_path=config_path, level=log_level)
    port = read_port_from_config(config_path=config_path, port=port)

    # Track run command
    telemetry.track_command(
        "run",
        {
            "script": script,
            "port": port,
            "log_level": log_level,
            "disable_new_tab": disable_new_tab,
        },
    )

    url = f"http://localhost:{port}"
    click.echo(f"Running '{script}' on {url} with log level {log_level}  🎉!")

    try:
        if not disable_new_tab:
            import webbrowser

            webbrowser.open(url)

        start_server(script=script, port=port)

    except Exception as e:
        click.echo(f"Error: {e}")


@cli.command()
@click.argument("script", default=None, required=False)
@click.option(
    "--target",
    type=click.Choice(["local", "gcp", "aws"], case_sensitive=False),
    default="local",
    help="Target platform for deployment.",
)
@click.option("--port", default=8501, help="Port for deployment.")
@click.option(
    "--log-level",
    type=click.Choice(
        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False
    ),
    default=None,
    help="Set the logging level (overrides config file)",
)
def deploy(script, target, port, log_level, github, api_key):  # noqa: C901
    """
    Deploy your Preswald app.

    This allows you to share the app within your local network or deploy to production.
    If no script is provided, it will use the entrypoint defined in preswald.toml.
    """
    try:
        if target == "aws":
            click.echo(
                "\nWe're working on supporting AWS soon! Please enjoy some ☕ and 🍌 in the meantime"
            )
            return

        # First try to read from preswald.toml in current directory
        config_path = "preswald.toml"
        if os.path.exists(config_path):
            import tomli

            try:
                with open(config_path, "rb") as f:
                    config = tomli.load(f)
                if "project" in config and "entrypoint" in config["project"]:
                    script = script or config["project"]["entrypoint"]
            except Exception as e:
                click.echo(f"Warning: Error reading preswald.toml: {e}")
                # Continue with provided script argument if config reading fails

        if not script:
            click.echo(
                "Error: No script specified and no entrypoint found in preswald.toml ❌"
            )
            click.echo(
                "Either provide a script argument or define entrypoint in preswald.toml"
            )
            return

        if not os.path.exists(script):
            click.echo(f"Error: Script '{script}' not found. ❌")
            return

        from preswald.deploy import deploy as deploy_app
        from preswald.utils import configure_logging, read_port_from_config

        config_path = os.path.join(os.path.dirname(script), "preswald.toml")
        log_level = configure_logging(config_path=config_path, level=log_level)
        port = read_port_from_config(config_path=config_path, port=port)

        # Track deployment
        telemetry.track_command(
            "deploy",
            {
                "script": script,
                "target": target,
                "port": port,
                "log_level": log_level,
                "has_github": bool(github),
                "has_api_key": bool(api_key),
            },
        )

        url = deploy_app(script, target, port=port)

        # Deployment Success Message
        success_message = f"""

        ===========================================================\n
        🎉 Deployment successful! ✅

        🌐 Your app is live and running at:
        {url}

        💡 Next Steps:
            - Open the URL above in your browser to view your app

        🚀 Deployment Summary:
            - App: {script}
            - Environment: {target}
            - Port: {port}
        """

        click.echo(click.style(success_message, fg="green"))

    except Exception as e:
        click.echo(click.style(f"Deployment failed: {e!s} ❌", fg="red"))
        sys.exit(1)


@cli.command()
@click.option(
    "--target",
    type=click.Choice(["local", "gcp", "aws"], case_sensitive=False),
    default="local",
    help="Target platform to stop the deployment from.",
)
def stop(target):
    """
    Stop the currently running deployment.

    This command must be run from the same directory as your Preswald app.
    """
    try:
        from preswald.deploy import cleanup_gcp_deployment

        # Track stop command
        telemetry.track_command("stop", {"target": target})
        config_path = "preswald.toml"
        if not os.path.exists(config_path):
            click.echo("Error: preswald.toml not found in current directory. ❌")
            click.echo("Make sure you're in a Preswald project directory.")
            return

        current_dir = os.getcwd()
        print(f"Current directory: {current_dir}")
        if target == "gcp":
            try:
                click.echo("Starting GCP deployment cleanup... 🧹")
                for status_update in cleanup_gcp_deployment(current_dir):
                    status = status_update.get("status", "")
                    message = status_update.get("message", "")

                    if status == "error":
                        click.echo(click.style(f"❌ {message}", fg="red"))
                    elif status == "success":
                        click.echo(click.style(f"✅ {message}", fg="green"))
                    else:
                        click.echo(f"i {message}")
                click.echo(
                    click.style(
                        "✅ GCP deployment cleaned up successfully!", fg="green"
                    )
                )
            except Exception as e:
                click.echo(click.style(f"❌ GCP cleanup failed: {e!s}", fg="red"))
                sys.exit(1)
        else:
            from preswald.deploy import stop_local_deployment

            stop_local_deployment(current_dir)
            click.echo("Deployment stopped successfully. 🛑 ")
    except Exception:
        sys.exit(1)

@cli.command()
@click.pass_context
def tutorial(ctx):
    """
    Run the Preswald tutorial app.

    This command runs the tutorial app located in the package's tutorial directory.
    """
    import preswald

    package_dir = os.path.dirname(preswald.__file__)
    tutorial_dir = os.path.join(package_dir, "tutorial")

    if not os.path.exists(tutorial_dir):
        click.echo(f"Error: Tutorial directory '{tutorial_dir}' not found. ❌")
        click.echo("👉 The tutorial files may be missing from your installation.")
        return

    # Track tutorial command
    telemetry.track_command("tutorial", {})

    click.echo("🚀 Launching the Preswald tutorial app! 🎉")

    # Save current directory
    current_dir = os.getcwd()
    try:
        # Change to tutorial directory
        os.chdir(tutorial_dir)
        # Invoke the 'run' command from the tutorial directory
        ctx.invoke(run, port=8501)
    finally:
        # Change back to original directory
        os.chdir(current_dir)


if __name__ == "__main__":
    cli()
