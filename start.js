// Pinokio : lance MediaVior et affiche son adresse dans le menu.
module.exports = {
  daemon: true,
  run: [
    {
      method: "shell.run",
      params: {
        venv: "env",
        message: ["python mediavior.py --sans-fenetre --sans-maj"],
        on: [{ event: "/(http:\\/\\/127\\.0\\.0\\.1:[0-9]+\\/)/", done: true }],
      },
    },
    { method: "local.set", params: { url: "{{input.event[1]}}" } },
  ],
};
