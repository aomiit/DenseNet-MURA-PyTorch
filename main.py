{
 "cells": [
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": [
    "import os\n",
    "import time\n",
    "import copy\n",
    "from glob import glob\n",
    "import random\n",
    "import numpy as np\n",
    "import pandas as pd\n",
    "import matplotlib.pyplot as plt\n",
    "from skimage import io, transform\n",
    "from tqdm import tqdm\n",
    "import torch\n",
    "import torch.nn as nn\n",
    "from torch.optim import Adam\n",
    "from torch.optim.lr_scheduler import ReduceLROnPlateau\n",
    "from torch.autograd import Variable\n",
    "from torch.utils.data import DataLoader, Dataset\n",
    "import torchvision\n",
    "from torchvision import transforms\n",
    "from torchvision.utils import make_grid\n",
    "from torchvision.datasets.folder import pil_loader\n",
    "\n",
    "from densenet import densenet169\n",
    "from utils import plot_training\n",
    "\n",
    "%matplotlib inline"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Prepare Data pipeline"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "data_cat = ['train', 'valid'] # data categories\n",
    "study_data = {}\n",
    "for phase in data_cat:\n",
    "    BASE_DIR = 'MURA-v1.0/%s/XR_WRIST/' %(phase)\n",
    "    patients = list(os.walk(BASE_DIR))[0][1]\n",
    "    study_data[phase] = pd.DataFrame(columns=['Path', 'Count', 'Label'])\n",
    "    study_label = {'positive': 0, 'negative': 1}\n",
    "    i = 0\n",
    "    for patient in tqdm(patients):\n",
    "        for study_type in os.listdir(BASE_DIR + patient):\n",
    "            label = study_label[study_type.split('_')[1]]\n",
    "            path = BASE_DIR + patient + '/' + study_type + '/'\n",
    "            study_data[phase].loc[i] = [path, len(os.listdir(path)), label]\n",
    "            i+=1"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": [
    "class StudyImageDataset(Dataset):\n",
    "    \"\"\"training dataset.\"\"\"\n",
    "\n",
    "    def __init__(self, df, transform=None):\n",
    "        \"\"\"\n",
    "        Args:\n",
    "            df (pd.DataFrame): a pandas DataFrame with image path and labels.\n",
    "            transform (callable, optional): Optional transform to be applied\n",
    "                on a sample.\n",
    "        \"\"\"\n",
    "        self.df = df\n",
    "        self.transform = transform\n",
    "\n",
    "    def __len__(self):\n",
    "        return len(self.df)\n",
    "\n",
    "    def __getitem__(self, idx):\n",
    "        study_path = self.df.iloc[idx, 0]\n",
    "        count = self.df.iloc[idx, 1]\n",
    "        images = []\n",
    "        for i in range(count):\n",
    "            image = pil_loader(study_path + 'image%s.png' % (i+1))\n",
    "            images.append(self.transform(image))\n",
    "        images = torch.stack(images)\n",
    "        label = self.df.iloc[idx, 2]\n",
    "        sample = {'images': images, 'label': label}\n",
    "        return sample"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": [
    "data_transforms = {\n",
    "    'train': transforms.Compose([\n",
    "            transforms.Resize((224, 224)),\n",
    "            transforms.RandomHorizontalFlip(),\n",
    "            transforms.RandomRotation(10),\n",
    "            transforms.ToTensor(), # coverts to tensor, scales to [0, 1]\n",
    "            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]) \n",
    "    ]),\n",
    "    'valid': transforms.Compose([\n",
    "        transforms.Resize((224, 224)),\n",
    "        transforms.ToTensor(),\n",
    "        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])\n",
    "    ]),\n",
    "}\n",
    "image_datasets = { x: StudyImageDataset(study_data[x], transform=data_transforms[x]) for x in data_cat}\n",
    "dataloaders = {x: DataLoader(image_datasets[x], batch_size=1, shuffle=True, num_workers=4) for x in data_cat}"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": [
    "dataset_sizes = {x: len(study_data[x]) for x in data_cat}\n",
    "use_gpu = torch.cuda.is_available()"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "next(iter(dataloaders['train']))['images'][0].shape"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {
    "collapsed": true
   },
   "source": [
    "### Building the model"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": [
    "def n_p(x):\n",
    "    '''convert numpy float to Variable tensor float'''\n",
    "    if use_gpu:\n",
    "        return Variable(torch.cuda.FloatTensor([x]), requires_grad=False)\n",
    "    else:\n",
    "        return Variable(torch.FloatTensor([x]), requires_grad=False)    "
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "# tai = total abnormal studies, tni = total normal studies\n",
    "\n",
    "tai = {x: study_data[x]['Label'].value_counts()[1] for x in data_cat}\n",
    "tni = {x: study_data[x]['Label'].value_counts()[0] for x in data_cat}\n",
    "\n",
    "Wt1 = {x: n_p(tni[x] / (tni[x] + tai[x])) for x in data_cat}\n",
    "Wt0 = {x: n_p(tai[x] / (tni[x] + tai[x])) for x in data_cat}\n",
    "\n",
    "\n",
    "print('tai:', tai)\n",
    "print('tni:', tni, '\\n')\n",
    "print('Wt0:', Wt0, '\\n')\n",
    "print('Wt1:', Wt1)"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": [
    "def update_TP_TN(outputs, labels_data, TP, TN):\n",
    "    '''\n",
    "    Takes output and label_data and calculates TP and TN\n",
    "    '''\n",
    "    sum_array = (outputs + labels_data).cpu().numpy()\n",
    "    TP += np.count_nonzero(sum_array == 2) # predicted = label = 1 and 1+1 = 2\n",
    "    TN += np.count_nonzero(sum_array == 0) # predicted = label = 0 and 0+0 = 0\n",
    "    return TP, TN"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": [
    "class Loss(nn.modules.Module):\n",
    "    def __init__(self, Wt1, Wt0):\n",
    "        super(Loss, self).__init__()\n",
    "        self.Wt1 = Wt1\n",
    "        self.Wt0 = Wt0\n",
    "        \n",
    "    def forward(self, inputs, targets, phase):\n",
    "        loss = - 1/len(inputs) * (self.Wt1[phase] * targets * inputs.log() + \n",
    "                                  self.Wt0[phase] * (1 - targets) * (1 - inputs).log())\n",
    "        return loss"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": [
    "def train_model(model, criterion, optimizer, num_epochs=25, scheduler=None):\n",
    "    since = time.time()\n",
    "\n",
    "    best_model_wts = copy.deepcopy(model.state_dict())\n",
    "    best_acc = 0.0\n",
    "    costs = {x:[] for x in data_cat} # for storing costs per epoch\n",
    "    accs = {x:[] for x in data_cat} # for storing accuracies per epoch\n",
    "    print('Train batches:', len(dataloaders['train']))\n",
    "    print('Valid batches:', len(dataloaders['valid']), '\\n')\n",
    "    for epoch in range(num_epochs):\n",
    "        print('Epoch {}/{}'.format(epoch, num_epochs - 1))\n",
    "        print('-' * 10)\n",
    "        # Each epoch has a training and validation phase\n",
    "        for phase in ['train', 'valid']:\n",
    "            TP, TN = 0, 0\n",
    "            if phase == 'train':\n",
    "#                 scheduler.step()\n",
    "                model.train(True)  # Set model to training mode\n",
    "            else:\n",
    "                model.train(False)  # Set model to evaluate mode\n",
    "\n",
    "            running_loss = 0.0\n",
    "            running_corrects = 0\n",
    "\n",
    "            # Iterate over data.\n",
    "            for i, data in enumerate(dataloaders[phase]):\n",
    "                # get the inputs\n",
    "                print(i, end='\\r')\n",
    "                inputs = data['images'][0]\n",
    "                labels = data['label']\n",
    "                # wrap them in Variable\n",
    "                if use_gpu:\n",
    "                    inputs = Variable(inputs.cuda())\n",
    "                    labels = data['label'].type(torch.FloatTensor)\n",
    "                    labels = Variable(labels.cuda())\n",
    "                else:\n",
    "                    inputs = Variable(inputs)\n",
    "                    labels = Variable(labels).type(torch.FloatTensor)\n",
    "\n",
    "                # zero the parameter gradients\n",
    "                optimizer.zero_grad()\n",
    "\n",
    "                # forward\n",
    "                outputs = model(inputs)\n",
    "                outputs = torch.mean(outputs)\n",
    "                loss = criterion(outputs, labels, phase)\n",
    "                \n",
    "                # backward + optimize only if in training phase\n",
    "                if phase == 'train':\n",
    "                    loss.backward()\n",
    "                    optimizer.step()\n",
    "                    \n",
    "                # statistics\n",
    "                running_loss += loss.data[0] * inputs.size(0)\n",
    "                if use_gpu:\n",
    "                    preds = (outputs.data > 0.5).type(torch.cuda.FloatTensor)\n",
    "                else:\n",
    "                    preds = (outputs.data > 0.5).type(torch.FloatTensor)\n",
    "                running_corrects += torch.sum(preds == labels.data)\n",
    "                TP, TN = update_TP_TN(preds, labels.data, TP, TN)\n",
    "\n",
    "            epoch_loss = running_loss / dataset_sizes[phase]\n",
    "            epoch_acc = running_corrects / dataset_sizes[phase]\n",
    "            sensitivity = TP / tai[phase]\n",
    "            specificity = TN / tni[phase]\n",
    "            \n",
    "            costs[phase].append(epoch_loss)\n",
    "            accs[phase].append(epoch_acc)\n",
    "            \n",
    "            print('{} Loss: {:.4f} Acc: {:.4f}'.format(\n",
    "                phase, epoch_loss, epoch_acc))\n",
    "            print('{} Sensitivity : {:.4f} Specificity: {:.4f}'.format(\n",
    "                phase, sensitivity, specificity))\n",
    "\n",
    "            # deep copy the model\n",
    "            if phase == 'val':\n",
    "                if epoch_acc > best_acc:\n",
    "                    best_acc = epoch_acc\n",
    "                    best_model_wts = copy.deepcopy(model.state_dict())\n",
    "                scheduler.step(epoch_loss)\n",
    "        print()\n",
    "\n",
    "    time_elapsed = time.time() - since\n",
    "    print('Training complete in {:.0f}m {:.0f}s'.format(\n",
    "        time_elapsed // 60, time_elapsed % 60))\n",
    "    print('Best val Acc: {:4f}'.format(best_acc))\n",
    "    \n",
    "#     plot_training(costs, accs)\n",
    "    # load best model weights\n",
    "    model.load_state_dict(best_model_wts)\n",
    "    return model"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": [
    "model = densenet169(pretrained=True)\n",
    "if use_gpu:\n",
    "    model = model.cuda()"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "criterion = Loss(Wt1, Wt0)\n",
    "optimizer = Adam(model.parameters(), lr=0.0001)\n",
    "scheduler = ReduceLROnPlateau(optimizer, mode='min', patience=1, verbose=True)"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "model = train_model(model, criterion, optimizer, num_epochs=4)"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": [
    "torch.save(model.state_dict(), 'models/v2.0.pth')"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": [
    "# model.load_state_dict(torch.load('models/v1.pth'))"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "### Model architecture used in this code"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": [
    "model"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 2,
   "metadata": {},
   "outputs": [
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "[NbConvertApp] Converting notebook v2.ipynb to script\n",
      "[NbConvertApp] Writing 8865 bytes to v2.py\n"
     ]
    }
   ],
   "source": [
    "!jupyter nbconvert --to script v2.ipynb"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": []
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {
    "collapsed": true
   },
   "outputs": [],
   "source": []
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python [default]",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.5.3"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 2
}
