set -e

if command -v apt-get >/dev/null 2>&1; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        git \
        cmake \
        python3 \
        python3-pip \
        build-essential \
        ninja-build \
        pkg-config \
        zlib1g-dev \
        libusb-1.0-0-dev \
        gcc-arm-none-eabi \
        libnewlib-arm-none-eabi \
        qtbase5-dev \
        qtdeclarative5-dev \
        qttools5-dev \
        qttools5-dev-tools \
        libqcustomplot-dev \
elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --noconfirm --needed --quiet \
        git \
        cmake \
        python \
        python-pip \
        base-devel \
        ninja \
        pkgconf \
        zlib \
        libusb \
        arm-none-eabi-gcc \
        arm-none-eabi-newlib \
        qt5-base \
        qt5-declarative \
        qt5-tools \
        qcustomplot \
else
    exit 1
fi

mkdir -p "$HOME/u-ndt-tools"

if [ ! -d "$HOME/u-ndt-tools/pico-sdk" ]; then
    git clone --quiet --recursive https://github.com/raspberrypi/pico-sdk.git "$HOME/u-ndt-tools/pico-sdk"
fi

printf 'export PICO_SDK_PATH="%s/u-ndt-tools/pico-sdk"\n' "$HOME" > "$HOME/u-ndt-tools/env.sh"
pip install -r ../python-tools/requirements.txt
