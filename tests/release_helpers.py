"""A stand-in for GitHub's data releases, shared by the mirror and data-home tests."""

import zipfile


def make_release_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)


class FakeGitHub:
    """Stands in for the two network calls: the newest tag and its data.zip."""

    def __init__(self, tmp_path, tag, files):
        self.tmp_path = tmp_path
        self.tag = tag
        self.files = files
        self.downloads = 0

    def latest_tag(self):
        return self.tag

    def download(self, tag, dest):
        assert tag == self.tag
        self.downloads += 1
        make_release_zip(dest, self.files)
