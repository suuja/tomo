from skimage.io import imread
from skimage.transform import radon, rescale
import warnings
import numpy as np
import pywt
#from scipy.sparse import csc_matrix,csc_matrix,lil_matrix
from scipy.optimize import  minimize
import time
import math
import scipy.sparse as sp
import os
import matplotlib.pyplot as plt
from cyt import tfun_cauchy as lcauchy, tfun_tikhonov as ltikhonov, tikhonov_grad,tfun_tv as ltv, tv_grad ,cauchy_grad,argumentspack



class tomography:

    def __init__(self, filename,scaling=0.1,ntheta=40,noise=0.000000):
        self.image = imread(filename, as_gray=True)
        self.image = rescale(self.image, scale=scaling, mode='edge', multichannel=False)
        (self.dim, self.dimx) = self.image.shape
        if (self.dim != self.dimx):
            raise Exception('Image is not rectangular.')
        self.theta = np.linspace(0., 179., ntheta, endpoint=True)
        self.theta=self.theta/360*2*np.pi
        self.flattened = np.reshape(self.image, (-1, 1))
        (self.N_r, self.N_theta) = (math.ceil(np.sqrt(2)*self.dim),ntheta)#self.radonww(self.image, self.theta, circle=True)).shape
        fname = 'radonmatrix/'+ 'full-' +str(self.dim) + 'x' + str(self.N_theta) + '.npz'

        #fname = 'koe.npz'

        if (not os.path.isfile(fname)):
            # M = np.zeros([self.N_r * self.N_theta, self.dim * self.dim])
            # #M = sp.lil_matrix((self.N_r * self.N_theta, self.dim * self.dim))
            # empty = np.zeros([self.dim, self.dim])
            # for i in range(0, self.dim):
            #     for j in range(0, self.dim):
            #         empty[i, j] = 1
            #         ww = np.ravel(np.reshape(radon(empty, self.theta, circle=False), (self.N_r * self.N_theta, 1)))
            #         M[:, i * self.dim + j] = ww# np.reshape(radon(empty, self.theta, circle=False), (self.N_r * self.N_theta, 1))
            #         empty[i, j] = 0
            # M = sp.csc_matrix(M)
            # sp.save_npz(fname,M)
            from matrices import radonmatrix

            self.radonoperator= radonmatrix(self.dim, self.theta)
            sp.save_npz(fname,self.radonoperator)

        self.radonoperator = sp.load_npz(fname)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        #self.radonoperator = loaded['radonoperator']
        #loaded.close()

        # self.measurement = np.exp(-self.radonoperator @ self.flattened) + noise * np.random.randn(self.N_r * self.N_theta, 1)
        # self.measurement[self.measurement<=0] = 10**(-19)
        # self.lines = -np.log(self.measurement)

        self.measurement = self.radonoperator @ self.flattened

        #self.measurement[self.measurement <= 0] = 10 ** (-19)
        max = np.max(self.measurement)
        self.lines =  self.measurement + max*noise * np.random.randn(self.N_r * self.N_theta, 1)
        self.sgram = np.reshape(self.lines,(self.N_r,self.N_theta))
        self.lhsigmsq = 0.5
        self.beta = 0.01
        self.Q = argumentspack(M=self.radonoperator,y=self.lines,b=self.beta,s2=self.lhsigmsq)

    def map_tikhonov(self,alpha=1.0):
        #col = np.block([[-1], [np.zeros((self.y - 2, 1))]])
        #row = np.block([np.array([-1,2,-1]),np.zeros((self.x-4,))])
        # d1= circulant(np.block([[2], [-1] , [np.zeros((self.dim - 3, 1))], [-1]]))
        # self.regx = np.kron(np.eye(self.dim), d1)
        # self.regy =  np.kron(d1, np.eye(self.dim))
        regvalues = np.array([2, -1, -1, -1, -1])
        offsets = np.array([0, 1, -1, self.dim - 1, -self.dim + 1])
        reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        self.regx = sp.kron(sp.eye(self.dim), reg1d)
        self.regy = sp.kron(reg1d, sp.eye(self.dim))
        self.alpha = alpha
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        self.regx = sp.csc_matrix(self.regx)
        self.regy = sp.csc_matrix(self.regy)
        self.Q.Lx = self.regx
        self.Q.Ly = self.regy
        self.Q.a = self.alpha
        self.Q.s2 = self.lhsigmsq
        # import scipy
        # b = np.block([[self.lines], [np.zeros((self.dim * self.dim, 1))]])
        # A = np.block([[self.radonoperator],[ np.sqrt(self.alpha)*self.regoperator]])
        # A = scipy.sparse.csc_matrix(A)
        # solution = scipy.sparse.linalg.lsqr(A, b)
        # solution = np.reshape(solution[0],(self.dim,self.dim))

        #

        x0= 1+ 0.05*np.random.randn(self.dim * self.dim, )
        solution = minimize(self.tfun_tikhonov,x0,method='L-BFGS-B',jac=self.grad_tikhonov,options={'maxiter':20, 'disp': True})
        solution = solution.x
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))

        #plt.imshow(solution, cmap="gray")
        #plt.show()
        return  solution


    def tfun_tikhonov(self,x):
        return -ltikhonov(x,self.Q)
        # x = np.reshape(x, (-1, 1))
        # Mxy = self.radonoperator.dot(x) - self.lines
        # # Lxx = np.dot(Lx,x)
        # Lxx = self.regx.dot(x)
        # # Lyx = np.dot(Ly,x)
        # Lyx = self.regy.dot(x)
        # return 0.5/self.lhsigmsq * np.dot(Mxy.T, Mxy) + self.alpha*np.dot(Lxx.T,Lxx) + self.alpha*np.dot(Lyx.T,Lyx)
        #return np.sum(np.array([a,b1,b2]))

    def grad_tikhonov(self,x):
        x = x.reshape((-1, 1))
        # print(self.radonoperator.shape,x.shape)
        ans = -tikhonov_grad(x, self.Q)
        # print(np.ravel(q))
        return (np.ravel(ans))

    def map_tv(self,alpha=1.0):
        # reg1d= circulant(np.block([[-1], [0], [np.zeros((self.dim - 3, 1))], [1]]))
        # self.regx = np.kron(np.eye(self.dim), reg1d)
        # self.regy = np.kron(reg1d,np.eye(self.dim))

        regvalues = np.array([1, -1, 1])
        offsets = np.array([-self.dim + 1, 0, 1])
        reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        self.regx = sp.kron(sp.eye(self.dim), reg1d)
        self.regy = sp.kron(reg1d, sp.eye(self.dim))
        self.regx = sp.csc_matrix(self.regx)
        self.regy = sp.csc_matrix(self.regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        self.alpha = alpha
        self.Q.Lx = self.regx
        self.Q.Ly = self.regy
        self.Q.a = self.alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.b = self.beta

        x0 = 1 + 0.05 * np.random.randn(self.dim * self.dim, )
        solution = minimize(self.tfun_tv, x0, method='L-BFGS-B', jac=self.grad_tv, options={'maxiter':230,'disp': True})
        solution = solution.x
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))

        #plt.imshow(solution, cmap="gray")
        #plt.show()
        return solution

    def tfun_tv(self, x):
        return -ltv(x, self.Q)
        # x = np.reshape(x, (-1, 1))
        # Mxy = self.radonoperator.dot(x) - self.lines
        # # Lxx = np.dot(Lx,x)
        # Lxx = self.regx.dot(x)
        # # Lyx = np.dot(Ly,x)
        # Lyx = self.regy.dot(x)
        # q =  0.5/self.lhsigmsq * np.dot(Mxy.T, Mxy) + self.alpha * np.sum(np.sqrt(np.power(Lxx, 2) + self.beta)) + self.alpha * np.sum(
        #     np.sqrt(np.power(Lyx, 2) + self.beta))
        # return (np.ravel(q))
        #return r

    def grad_tv(self, x):
        x = x.reshape((-1, 1))
        # print(self.radonoperator.shape,x.shape)
        q = -tv_grad(x, self.Q)
        #print(np.ravel(q))
        return (np.ravel(q))

    def map_cauchy(self,alpha=1.0):
        # reg1d= circulant(np.block([[-1], [0], [np.zeros((self.dim - 3, 1))], [1]]))
        # self.regx = sp.kron(sp.eye(self.dim), reg1d)
        # self.regy = sp.kron(reg1d,sp.eye(self.dim))
        #plt.spy(self.radonoperator)
        #print(np.sum(self.radonoperator[:,1000]))
        #plt.show()
        regvalues = np.array([1, -1, 1])
        offsets = np.array([-self.dim + 1, 0, 1])
        reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        self.regx = sp.kron(sp.eye(self.dim), reg1d)
        self.regy = sp.kron(reg1d, sp.eye(self.dim))
        self.regx = sp.csc_matrix(self.regx)
        self.regy = sp.csc_matrix(self.regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        self.alpha = alpha
        self.Q.Lx = self.regx
        self.Q.Ly = self.regy
        self.Q.a = self.alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.b = self.beta
        #print(self.radonoperator.shape)
        #print(self.regx.shape)
        x0 = 1 + 0.05 * np.random.randn(self.dim * self.dim, )
        bnds = [(0, np.inf) for _ in x0]

        solution = minimize(self.tfun_cauchy, x0, method='L-BFGS-B', jac=self.grad_cauchy, options={'maxiter':150,'disp': True})
        solution = solution.x
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))

        #plt.imshow(solution, cmap="gray")
        #plt.show()
        return solution

    def tfun_cauchy(self, x):
        return -lcauchy(x,self.Q)
        # x = np.reshape(x, (-1, 1))
        # Mxy = self.radonoperator.dot(x) - self.lines
        # Lxx = self.regx.dot(x)
        # # Lyx = np.dot(Ly,x)
        # Lyx = self.regy.dot(x)
        # return   0.5/self.lhsigmsq*np.dot(Mxy.T, Mxy) + np.sum(np.log(self.alpha + np.power(Lyx, 2))) + np.sum(
        #     np.log(self.alpha + np.power(Lxx, 2)))
        #return r

    def grad_cauchy(self, x):
        x = x.reshape((-1,1))
        #print(self.radonoperator.shape,x.shape)
        ans  =  -cauchy_grad(x,self.Q)
        #print(np.ravel(q))
        return (np.ravel(ans))

    def map_wavelet(self,alpha=1.0,type='haar'):
        from matrices import totalmatrix
        wl = pywt.Wavelet(type)
        g = np.array(wl.dec_lo)
        h = np.array(wl.dec_hi)
        self.regx = totalmatrix(self.dim,6,g,h)
        self.regy = sp.csc_matrix((1,self.dim*self.dim))
        self.regx = sp.csc_matrix(self.regx)
        self.regy = sp.csc_matrix(self.regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        self.beta = 0
        self.alpha = alpha
        self.Q.Lx = self.regx
        self.Q.Ly = self.regy
        self.Q.a = self.alpha
        self.Q.s2 = self.lhsigmsq

        x0 = 1 + 0.05 * np.random.randn(self.dim * self.dim, )
        solution = minimize(self.tfun_tv, x0, method='L-BFGS-B', jac=self.grad_tv,
                            options={'maxiter': 230, 'disp': True})
        solution = solution.x
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))

        # plt.imshow(solution, cmap="gray")
        # plt.show()
        return solution

    def hmcmc_tikhonov(self,alpha,M=100,Madapt=20):
        from cyt import hmc
        regvalues = np.array([2, -1, -1, -1, -1])
        offsets = np.array([0, 1, -1, self.dim - 1, -self.dim + 1])
        reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        self.regx = sp.kron(sp.eye(self.dim), reg1d)
        self.regy = sp.kron(reg1d, sp.eye(self.dim))
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        self.alpha = alpha
        self.Q.Lx = self.regx
        self.Q.Ly = self.regy
        self.Q.a = self.alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.b = self.beta
        self.Q.logdensity = ltikhonov
        self.Q.gradi = tikhonov_grad
        # print(self.radonoperator.shape)
        # print(self.regx.shape)
        #x0 = np.reshape(self.map_tikhonov(alpha),(-1,1))
        #x0 = x0 + 1*np.random.rand(self.dim*self.dim,1)
        x0 = 0.2*np.ones((self.dim * self.dim, 1))
        cm = hmc(M,x0,self.Q,Madapt,de=0.6,cm=True)
        cm = np.reshape(cm, (-1, 1))
        cm = np.reshape(cm, (self.dim, self.dim))
        return cm

    def mwg_tv(self,alpha,M=100,Madapt=20):
        from cyt import mwg_tv, mwg_cauchy
        regvalues = np.array([1, -1, 1])
        offsets = np.array([-self.dim + 1, 0, 1])
        reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        self.regx = sp.kron(sp.eye(self.dim), reg1d)
        self.regy = sp.kron(reg1d, sp.eye(self.dim))
        self.regx = sp.csc_matrix(self.regx)
        self.regy = sp.csc_matrix(self.regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        self.alpha = alpha
        self.Q.Lx = self.regx
        self.Q.Ly = self.regy
        self.Q.a = self.alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.b = self.beta
        self.Q.y = self.lines
        # print(self.radonoperator.shape)
        # print(self.regx.shape)
        #x0 = np.reshape(self.map_tikhonov(alpha),(-1,1))
        #x0 = x0 + 1*np.random.rand(self.dim*self.dim,1)
        x0 = 0.2*np.ones((self.dim * self.dim, 1))
        cm = mwg_tv(M,Madapt,self.Q, x0, sampsigma=1.0,cmesti=True)
        cm = np.reshape(cm, (-1, 1))
        cm = np.reshape(cm, (self.dim, self.dim))
        return cm

    def hmcmc_tv(self,alpha,M=100,Madapt=20):
        from cyt import hmc
        regvalues = np.array([1, -1, 1])
        offsets = np.array([-self.dim + 1, 0, 1])
        reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        self.regx = sp.kron(sp.eye(self.dim), reg1d)
        self.regy = sp.kron(reg1d, sp.eye(self.dim))
        self.regx = sp.csc_matrix(self.regx)
        self.regy = sp.csc_matrix(self.regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        self.alpha = alpha
        self.Q.Lx = self.regx
        self.Q.Ly = self.regy
        self.Q.a = self.alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.b = self.beta
        self.Q.logdensity = ltv
        self.Q.gradi = tv_grad
        # print(self.radonoperator.shape)
        # print(self.regx.shape)
        #x0 = np.reshape(self.map_tv(alpha),(-1,1))
        #x0 = x0 + 0.1*np.random.randn(self.dim*self.dim,1)
        x0 = 0.2*np.ones((self.dim * self.dim, 1))
        cm = hmc(M,x0,self.Q,Madapt,de=0.6,cm=True)
        cm = np.reshape(cm, (-1, 1))
        cm = np.reshape(cm, (self.dim, self.dim))
        return cm

    def hmcmc_cauchy(self,alpha,M=100,Madapt=20):
        from cyt import hmc
        regvalues = np.array([1, -1, 1])
        offsets = np.array([-self.dim + 1, 0, 1])
        reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        self.regx = sp.kron(sp.eye(self.dim), reg1d)
        self.regy = sp.kron(reg1d, sp.eye(self.dim))
        self.regx = sp.csc_matrix(self.regx)
        self.regy = sp.csc_matrix(self.regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        self.alpha = alpha
        self.Q.Lx = self.regx
        self.Q.Ly = self.regy
        self.Q.a = self.alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.b = self.beta
        self.Q.logdensity = lcauchy
        self.Q.gradi = cauchy_grad
        # print(self.radonoperator.shape)
        # print(self.regx.shape)
        #x0 = np.reshape(self.map_cauchy(alpha),(-1,1))
        #x0 = x0 + np.random.rand(self.dim*self.dim,1)
        x0 = 0.2*np.ones((self.dim * self.dim, 1))
        cm = hmc(M,x0,self.Q,Madapt,de=0.6,cm=True)
        cm = np.reshape(cm, (-1, 1))
        cm = np.reshape(cm, (self.dim, self.dim))
        return cm

    def target(self):
        return self.image

    def sinogram(self):
        return self.sgram

    def radonww(self,circle=False):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return radon(self.image,self.theta/(2*np.pi)*360,circle)


if __name__ == "__main__":

    #np.random.seed(1)
    t = tomography("shepp64.png",1.0,50,0.02)
    r = t.target()
    #sg = t.sinogram()
    #sg2 = t.radonww()
    #t = tomography("shepp.png",0.1,20,0.2)
    #r = t.mwg_tv(10,30000,2000)
    r = t.hmcmc_tv(10,500,300)
    #r = t.hmcmc_cauchy(1,350,300)
    #r = t.hmcmc_tikhonov(1, 500, 300)
    #print(np.linalg.norm(real - r))
    # tt = time.time()
    #

    # # print(time.time()-tt)
    # #
    plt.imshow(r)
    #plt.clim(0, 1)
    plt.figure()

    r = t.map_tv(10)
    #r = t.map_cauchy(1)
    #r = t.map_tikhonov(1.0)
    #print(np.linalg.norm(real - r))
    #q = iradon_sart(q, theta=theta)
    #r = t.map_tikhonov(50.0)
    #tt = time.time()
    #r = t.map_tikhonov(50)
    #r = t.map_wavelet(5,'db2')
    #print(np.linalg.norm(real-r))
    #print(time.time()-tt)
    plt.imshow(r)
    #plt.clim(0, 1)
    plt.show()


#
        #