// Pinokio : récupère la dernière version de MediaVior et de yt-dlp.
module.exports = {
  run: [
    { method: "shell.run", params: { message: "git pull" } },
    {
      method: "shell.run",
      params: {
        venv: "env",
        message: [
          "uv pip install -r requirements.txt -r requirements-local.txt",
          "uv pip install -U \"yt-dlp[default]\"",
        ],
      },
    },
  ],
};
